"""
BookingHandler: Phase 3 handler for booking items from approved itinerary.

Per design doc Three-Phase Workflow and Booking Safety sections:
- Orchestrates independent booking operations
- Uses BookingService for booking actions (view_booking_options, book_item, etc.)
- Tracks booking status in state
- Ensures booking failures don't affect other bookings

Actions handled:
- VIEW_BOOKING_OPTIONS: View bookable items with quotes
- BOOK_SINGLE_ITEM: Execute booking with quote validation
- RETRY_BOOKING: Retry a failed booking
- CANCEL_BOOKING: Cancel a booked item (if policy allows)
- CHECK_BOOKING_STATUS: Reconcile UNKNOWN/PENDING status
- CANCEL_UNKNOWN_BOOKING: Cancel UNKNOWN booking attempt
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.orchestrator.handlers.clarification import HandlerResult, PhaseHandler
from src.orchestrator.models.responses import ToolResponse, UIAction, UIDirective
from src.orchestrator.models.workflow_state import WorkflowState
from src.orchestrator.state_gating import Action, WorkflowEvent
from src.orchestrator.storage import WorkflowStateData

if TYPE_CHECKING:
    from src.orchestrator.booking.service import BookingService
    from src.orchestrator.storage.booking_store import BookingStoreProtocol
    from src.orchestrator.storage.consultation_summaries import (
        ConsultationSummaryStoreProtocol,
    )
    from src.orchestrator.storage.itinerary_store import ItineraryStoreProtocol

logger = logging.getLogger(__name__)


def _error_response(
    message: str,
    error_code: str | None = None,
    ui: UIDirective | None = None,
    data: dict[str, Any] | None = None,
) -> ToolResponse:
    """
    Create an error response with consistent structure.

    Uses ToolResponse with success=False and embeds error_code in data.
    """
    response_data = data.copy() if data else {}
    if error_code:
        response_data["error_code"] = error_code

    return ToolResponse(
        success=False,
        message=message,
        data=response_data if response_data else None,
        ui=ui,
    )


class BookingHandler(PhaseHandler):
    """
    Handles Phase 3: Booking.

    Per design doc Three-Phase Workflow section:
    - Booking phase has no checkpoint (free-form)
    - Each booking is independent (no cart)
    - Users can interleave questions between bookings
    - Failed bookings don't roll back successful ones

    This handler coordinates booking operations through BookingService,
    keeping the handler thin while BookingService handles the business logic.
    """

    def __init__(
        self,
        state: WorkflowState,
        state_data: WorkflowStateData,
        booking_service: "BookingService | None" = None,
        booking_store: "BookingStoreProtocol | None" = None,
        itinerary_store: "ItineraryStoreProtocol | None" = None,
        consultation_summary_store: "ConsultationSummaryStoreProtocol | None" = None,
    ):
        """
        Initialize the booking handler.

        Args:
            state: Domain model for validation and business logic
            state_data: Storage model for persistence
            booking_service: Service for booking operations (optional)
            booking_store: Store for booking data (used if booking_service not provided)
            itinerary_store: Store for itinerary data (used if booking_service not provided)
            consultation_summary_store: Store for consultation summaries (for completion updates)
        """
        super().__init__(state, state_data)
        self._booking_service = booking_service
        self._booking_store = booking_store
        self._itinerary_store = itinerary_store
        self._consultation_summary_store = consultation_summary_store

    def _get_booking_service(self) -> "BookingService | None":
        """
        Get or create BookingService.

        Lazy creation allows dependency injection for testing.
        """
        if self._booking_service is not None:
            return self._booking_service

        # Create BookingService if stores are available
        if self._booking_store is not None and self._itinerary_store is not None:
            from src.orchestrator.booking.service import BookingService
            self._booking_service = BookingService(
                booking_store=self._booking_store,
                itinerary_store=self._itinerary_store,
            )
            return self._booking_service

        return None

    async def execute(
        self,
        action: Action,
        message: str,
        event: WorkflowEvent | None = None,
    ) -> HandlerResult:
        """
        Execute the action for booking phase.

        Per design doc, valid actions in BOOKING phase:
        - VIEW_BOOKING_OPTIONS: View bookable items with quotes
        - BOOK_SINGLE_ITEM: Execute booking with quote validation
        - RETRY_BOOKING: Retry a failed booking
        - CANCEL_BOOKING: Cancel a booked item
        - CHECK_BOOKING_STATUS: Reconcile UNKNOWN/PENDING status
        - CANCEL_UNKNOWN_BOOKING: Cancel UNKNOWN booking attempt
        """
        match action:
            case Action.VIEW_BOOKING_OPTIONS:
                return await self._view_booking_options(event)

            case Action.BOOK_SINGLE_ITEM:
                return await self._book_single_item(event)

            case Action.RETRY_BOOKING:
                return await self._retry_booking(event)

            case Action.CANCEL_BOOKING:
                return await self._cancel_booking(event)

            case Action.CHECK_BOOKING_STATUS:
                return await self._check_booking_status(event)

            case Action.CANCEL_UNKNOWN_BOOKING:
                return await self._cancel_unknown_booking(event)

            case _:
                # Invalid action for this phase
                logger.warning(
                    "Invalid action %s for BOOKING phase, returning error",
                    action.value,
                )
                return HandlerResult(
                    response=_error_response(
                        message=f"Action '{action.value}' not valid in booking phase",
                        error_code="INVALID_ACTION_FOR_PHASE",
                    ),
                    state_data=self.state_data,
                )

    async def _view_booking_options(
        self,
        event: WorkflowEvent | None = None,
    ) -> HandlerResult:
        """
        View bookable items with current quotes.

        Per design doc:
        - No booking_id: returns all bookable items for the itinerary
        - With booking_id: returns single item quote card (drill-down)
        """
        booking_service = self._get_booking_service()

        # Extract booking_id from event if provided (for drill-down)
        booking_id: str | None = None
        if event and event.booking:
            booking_id = event.booking.get("booking_id")

        # If no BookingService, return stub response
        if booking_service is None:
            return self._create_stub_booking_options_response(booking_id)

        # Get itinerary_id from state
        itinerary_id = getattr(self.state, 'itinerary_id', None)

        if booking_id:
            # Single booking drill-down
            response = await booking_service.view_booking_options(
                booking_id=booking_id,
            )
        elif itinerary_id:
            # All bookings for itinerary
            response = await booking_service.view_booking_options(
                itinerary_id=itinerary_id,
            )
        else:
            response = _error_response(
                message="No itinerary found. Please complete trip planning first.",
                error_code="NO_ACTIVE_ITINERARY",
            )

        # Sync state to data
        self._sync_state_to_data()

        return HandlerResult(
            response=response,
            state_data=self.state_data,
        )

    async def _book_single_item(
        self,
        event: WorkflowEvent | None = None,
    ) -> HandlerResult:
        """
        Book a single item with quote validation.

        Per design doc Booking Safety section:
        - Requires booking_id and quote_id from event
        - Quote validation ensures user agreed to exact price/terms
        - Idempotent - safe to call multiple times with same quote_id
        """
        # Extract booking payload from event
        if event is None or event.booking is None:
            return HandlerResult(
                response=_error_response(
                    message="Booking payload required. Use view_booking_options first.",
                    error_code="MISSING_BOOKING_PAYLOAD",
                    ui=UIDirective(
                        actions=[
                            UIAction(
                                label="View Booking Options",
                                event={"type": "view_booking_options"},
                            ),
                        ],
                    ),
                ),
                state_data=self.state_data,
            )

        booking_id = event.booking.get("booking_id")
        quote_id = event.booking.get("quote_id")

        if not booking_id or not quote_id:
            return HandlerResult(
                response=_error_response(
                    message="Both booking_id and quote_id are required.",
                    error_code="MISSING_BOOKING_PAYLOAD",
                ),
                state_data=self.state_data,
            )

        booking_service = self._get_booking_service()

        if booking_service is None:
            return self._create_stub_book_item_response(booking_id, quote_id)

        # Execute booking
        response = await booking_service.book_item(
            booking_id=booking_id,
            quote_id=quote_id,
        )

        # Update booking tracking in state
        self._track_booking_status(booking_id, response)

        # Sync state to data
        self._sync_state_to_data()

        # Check if all bookings are now complete and update consultation summary
        await self._check_and_update_booking_completion()

        return HandlerResult(
            response=response,
            state_data=self.state_data,
        )

    async def _retry_booking(
        self,
        event: WorkflowEvent | None = None,
    ) -> HandlerResult:
        """
        Retry a failed booking with a fresh quote.

        Per design doc Booking Safety section:
        - Only allowed for FAILED bookings
        - Requires booking_id and fresh quote_id
        - Generates new idempotency key
        """
        if event is None or event.booking is None:
            return HandlerResult(
                response=_error_response(
                    message="Booking payload required for retry.",
                    error_code="MISSING_BOOKING_PAYLOAD",
                ),
                state_data=self.state_data,
            )

        booking_id = event.booking.get("booking_id")
        quote_id = event.booking.get("quote_id")

        if not booking_id or not quote_id:
            return HandlerResult(
                response=_error_response(
                    message="Both booking_id and quote_id are required for retry.",
                    error_code="MISSING_BOOKING_PAYLOAD",
                ),
                state_data=self.state_data,
            )

        # For now, retry uses same book_item flow
        # Full retry logic with FAILED status check will be in ORCH-052
        booking_service = self._get_booking_service()

        if booking_service is None:
            return self._create_stub_retry_response(booking_id)

        # Use book_item for now - full retry logic in ORCH-052
        response = await booking_service.book_item(
            booking_id=booking_id,
            quote_id=quote_id,
        )

        self._track_booking_status(booking_id, response)
        self._sync_state_to_data()

        # Check if all bookings are now complete and update consultation summary
        await self._check_and_update_booking_completion()

        return HandlerResult(
            response=response,
            state_data=self.state_data,
        )

    async def _cancel_booking(
        self,
        event: WorkflowEvent | None = None,
    ) -> HandlerResult:
        """
        Cancel a booked item (if cancellation policy allows).

        Per design doc Booking Safety section:
        - Only allowed for BOOKED items
        - Checks cancellation policy before proceeding
        - May require fee confirmation if past free cancellation window
        - Records refund metadata
        """
        if event is None or event.booking is None:
            return HandlerResult(
                response=_error_response(
                    message="Booking ID required for cancellation.",
                    error_code="MISSING_BOOKING_PAYLOAD",
                ),
                state_data=self.state_data,
            )

        booking_id = event.booking.get("booking_id")

        if not booking_id:
            return HandlerResult(
                response=_error_response(
                    message="Booking ID required for cancellation.",
                    error_code="MISSING_BOOKING_PAYLOAD",
                ),
                state_data=self.state_data,
            )

        # Extract confirm_fee from event (for cancellation fee confirmation)
        confirm_fee = event.booking.get("confirm_fee", False)

        booking_service = self._get_booking_service()

        if booking_service is None:
            return self._create_stub_cancel_booking_response(booking_id)

        # Execute cancellation via BookingService
        response = await booking_service.cancel_booking(
            booking_id=booking_id,
            confirm_fee=confirm_fee,
        )

        # Update booking tracking in state
        self._track_booking_status(booking_id, response)

        # Sync state to data
        self._sync_state_to_data()

        # Check if all bookings are now complete and update consultation summary
        await self._check_and_update_booking_completion()

        return HandlerResult(
            response=response,
            state_data=self.state_data,
        )

    async def _check_booking_status(
        self,
        event: WorkflowEvent | None = None,
    ) -> HandlerResult:
        """
        Check and reconcile booking status.

        Per design doc Booking Safety section:
        - Used to reconcile UNKNOWN/PENDING bookings
        - Queries provider using idempotency key
        - Updates booking status based on provider response

        Implemented in ORCH-089.
        """
        if event is None or event.booking is None:
            return HandlerResult(
                response=_error_response(
                    message="Booking ID required for status check.",
                    error_code="MISSING_BOOKING_PAYLOAD",
                ),
                state_data=self.state_data,
            )

        booking_id = event.booking.get("booking_id")

        if not booking_id:
            return HandlerResult(
                response=_error_response(
                    message="Booking ID required for status check.",
                    error_code="MISSING_BOOKING_PAYLOAD",
                ),
                state_data=self.state_data,
            )

        booking_service = self._get_booking_service()

        if booking_service is None:
            return self._create_stub_check_status_response(booking_id)

        # Execute status check
        response = await booking_service.check_booking_status(
            booking_id=booking_id,
        )

        # Update booking tracking in state
        self._track_booking_status(booking_id, response)

        # Sync state to data
        self._sync_state_to_data()

        # Check if all bookings are now complete and update consultation summary
        await self._check_and_update_booking_completion()

        return HandlerResult(
            response=response,
            state_data=self.state_data,
        )

    async def _cancel_unknown_booking(
        self,
        event: WorkflowEvent | None = None,
    ) -> HandlerResult:
        """
        Cancel an UNKNOWN booking attempt.

        Per design doc Booking Safety section:
        - Only allowed for UNKNOWN status
        - First reconciles with provider
        - If provider confirms, converts to BOOKED (don't cancel!)
        - If provider has no record, resets to FAILED and clears idempotency key
        - If provider still processing, blocks cancellation
        """
        if event is None or event.booking is None:
            return HandlerResult(
                response=_error_response(
                    message="Booking ID required to cancel unknown booking.",
                    error_code="MISSING_BOOKING_PAYLOAD",
                ),
                state_data=self.state_data,
            )

        booking_id = event.booking.get("booking_id")

        if not booking_id:
            return HandlerResult(
                response=_error_response(
                    message="Booking ID required to cancel unknown booking.",
                    error_code="MISSING_BOOKING_PAYLOAD",
                ),
                state_data=self.state_data,
            )

        booking_service = self._get_booking_service()

        if booking_service is None:
            return self._create_stub_cancel_unknown_response(booking_id)

        # Execute cancel_unknown_booking via BookingService
        response = await booking_service.cancel_unknown_booking(
            booking_id=booking_id,
        )

        # Update booking tracking in state
        self._track_booking_status(booking_id, response)

        # Sync state to data
        self._sync_state_to_data()

        # Check if all bookings are now complete and update consultation summary
        await self._check_and_update_booking_completion()

        return HandlerResult(
            response=response,
            state_data=self.state_data,
        )

    def _create_stub_cancel_unknown_response(
        self,
        booking_id: str,
    ) -> HandlerResult:
        """
        Create stub response for cancel_unknown_booking when no BookingService is available.
        """
        return HandlerResult(
            response=ToolResponse(
                success=True,
                message=f"Previous attempt cancelled. You can now book with a fresh quote.",
                data={
                    "booking_id": booking_id,
                    "status": "failed",
                    "stub": True,
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label="View Booking Options",
                            event={"type": "view_booking_options"},
                        ),
                    ],
                ),
            ),
            state_data=self.state_data,
        )

    def _create_stub_cancel_booking_response(
        self,
        booking_id: str,
    ) -> HandlerResult:
        """
        Create stub response for cancel_booking when no BookingService is available.
        """
        return HandlerResult(
            response=ToolResponse(
                success=True,
                message=f"Booking {booking_id} cancelled successfully.",
                data={
                    "booking_id": booking_id,
                    "cancellation_reference": f"CANCEL-{booking_id[-8:].upper()}",
                    "refund_amount": 450.00,
                    "stub": True,
                },
            ),
            state_data=self.state_data,
        )

    def _track_booking_status(
        self,
        booking_id: str,
        response: ToolResponse,
    ) -> None:
        """
        Track booking status changes in state.

        Updates the workflow state with booking status for tracking
        which bookings have succeeded, failed, or are pending.

        Args:
            booking_id: The booking that was processed
            response: The response from BookingService
        """
        # Initialize booking_status dict if needed
        if not hasattr(self.state, 'booking_status'):
            self.state.booking_status = {}

        # Extract status from response data
        status = "unknown"
        error_code = response.data.get("error_code") if response.data else None
        response_status = response.data.get("status") if response.data else None

        if response.success:
            # Check if response data has explicit status (e.g., "cancelled")
            if response_status == "cancelled":
                status = "cancelled"
            elif response.data and response.data.get("cancellation_reference"):
                # Cancellation successful
                status = "cancelled"
            else:
                status = "booked"
        elif error_code:
            if error_code == "BOOKING_IN_PROGRESS":
                status = "pending"
            elif error_code == "BOOKING_PENDING_RECONCILIATION":
                status = "unknown"
            elif error_code in ("BOOKING_FAILED", "BOOKING_CANCELLED"):
                status = "failed"
            else:
                # Quote-related errors don't change status
                pass

        # Update tracking
        self.state.booking_status[booking_id] = {
            "status": status,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        logger.debug(f"Tracked booking {booking_id} status: {status}")

    def _create_stub_booking_options_response(
        self,
        booking_id: str | None = None,
    ) -> HandlerResult:
        """
        Create stub response when no BookingService is available.

        Used for testing without real stores.
        """
        if booking_id:
            # Single booking view
            return HandlerResult(
                response=ToolResponse(
                    success=True,
                    message="Viewing booking details",
                    data={
                        "booking": {
                            "booking_id": booking_id,
                            "item_type": "hotel",
                            "status": "unbooked",
                            "price": 450.00,
                            "quote": {
                                "quote_id": "quote_stub123",
                                "quoted_price": 450.00,
                                "currency": "USD",
                                "expires_at": "2026-01-24T12:00:00Z",
                                "terms_summary": "Free cancellation until Jan 22",
                            },
                        },
                        "stub": True,
                    },
                    ui=UIDirective(
                        actions=[
                            UIAction(
                                label="Book for $450.00",
                                event={
                                    "type": "book_item",
                                    "booking": {
                                        "booking_id": booking_id,
                                        "quote_id": "quote_stub123",
                                    },
                                },
                            ),
                        ],
                        display_type="booking_options",
                    ),
                ),
                state_data=self.state_data,
            )

        # All bookings view
        return HandlerResult(
            response=ToolResponse(
                success=True,
                message="3 available to book, 0 booked, 0 pending",
                data={
                    "bookings": [
                        {
                            "booking_id": "book_stub1",
                            "item_type": "flight",
                            "status": "unbooked",
                            "price": 550.00,
                        },
                        {
                            "booking_id": "book_stub2",
                            "item_type": "hotel",
                            "status": "unbooked",
                            "price": 450.00,
                        },
                        {
                            "booking_id": "book_stub3",
                            "item_type": "activity",
                            "status": "unbooked",
                            "price": 75.00,
                        },
                    ],
                    "stub": True,
                },
                ui=UIDirective(
                    actions=[
                        UIAction(
                            label="Book Flight ($550)",
                            event={
                                "type": "book_item",
                                "booking": {
                                    "booking_id": "book_stub1",
                                    "quote_id": "quote_flight123",
                                },
                            },
                        ),
                        UIAction(
                            label="Book Hotel ($450)",
                            event={
                                "type": "book_item",
                                "booking": {
                                    "booking_id": "book_stub2",
                                    "quote_id": "quote_hotel123",
                                },
                            },
                        ),
                    ],
                    display_type="booking_options",
                ),
            ),
            state_data=self.state_data,
        )

    def _create_stub_book_item_response(
        self,
        booking_id: str,
        quote_id: str,
    ) -> HandlerResult:
        """
        Create stub booking response when no BookingService is available.
        """
        # Simulate successful booking
        booking_ref = f"REF-{booking_id[-8:].upper()}"

        return HandlerResult(
            response=ToolResponse(
                success=True,
                message=f"Booked! Confirmation: {booking_ref}",
                data={
                    "booking_id": booking_id,
                    "booking_reference": booking_ref,
                    "confirmed_price": 450.00,
                    "confirmed_terms": "Free cancellation until Jan 22",
                    "stub": True,
                },
            ),
            state_data=self.state_data,
        )

    def _create_stub_retry_response(
        self,
        booking_id: str,
    ) -> HandlerResult:
        """
        Create stub retry response when no BookingService is available.
        """
        return HandlerResult(
            response=ToolResponse(
                success=True,
                message=f"Retrying booking {booking_id}...",
                data={
                    "booking_id": booking_id,
                    "status": "retrying",
                    "stub": True,
                },
            ),
            state_data=self.state_data,
        )

    def _create_stub_check_status_response(
        self,
        booking_id: str,
    ) -> HandlerResult:
        """
        Create stub check status response when no BookingService is available.
        """
        return HandlerResult(
            response=ToolResponse(
                success=True,
                message=f"Checking status for booking {booking_id}... (stub)",
                data={
                    "booking_id": booking_id,
                    "status": "checking",
                    "stub": True,
                },
            ),
            state_data=self.state_data,
        )

    def _sync_state_to_data(self) -> None:
        """
        Sync WorkflowState changes back to WorkflowStateData.
        """
        # Update phase
        self.state_data.phase = self.state.phase.value

        # Update checkpoint and step
        self.state_data.checkpoint = self.state.checkpoint
        self.state_data.current_step = self.state.current_step

        # Update agent context IDs
        self.state_data.agent_context_ids = {
            name: state.to_dict()
            for name, state in self.state.agent_context_ids.items()
        }

        # Update itinerary_id if available
        if hasattr(self.state_data, 'itinerary_id') and hasattr(self.state, 'itinerary_id'):
            self.state_data.itinerary_id = self.state.itinerary_id

        # Update timestamp
        self.state_data.updated_at = datetime.now(timezone.utc)

    async def _check_and_update_booking_completion(self) -> bool:
        """
        Check if all bookings are in terminal state and update consultation summary.

        Per ORCH-107:
        - When all bookings reach a terminal state (BOOKED, FAILED, or CANCELLED),
          update the consultation_summaries with status="completed"
        - Does not modify WorkflowState beyond booking updates

        Returns:
            True if all bookings are terminal and summary was updated, False otherwise
        """
        booking_service = self._get_booking_service()
        if booking_service is None:
            logger.debug("No booking service available for completion check")
            return False

        if not self._consultation_summary_store:
            logger.debug("No consultation summary store available for completion update")
            return False

        # Get itinerary_id from state
        itinerary_id = getattr(self.state, 'itinerary_id', None)
        if not itinerary_id:
            logger.debug("No itinerary_id available for completion check")
            return False

        # Get booking summary to check terminal status
        try:
            summary = await booking_service.get_booking_summary(itinerary_id)
            if summary is None:
                logger.debug(f"No booking summary found for itinerary {itinerary_id}")
                return False

            # Check if all bookings are terminal
            if not summary.all_terminal:
                logger.debug(
                    f"Not all bookings terminal: {summary.pending_count} pending, "
                    f"{summary.unknown_count} unknown, {summary.unbooked_count} unbooked"
                )
                return False

            # All bookings are terminal - update consultation summary
            consultation_id = self.state.consultation_id
            if not consultation_id:
                logger.warning("No consultation_id available for summary update")
                return False

            # Get existing consultation summary
            existing_summary = await self._consultation_summary_store.get_summary(
                consultation_id
            )
            if existing_summary is None:
                logger.warning(
                    f"No consultation summary found for {consultation_id}"
                )
                return False

            # Update status to completed and update booking_ids
            existing_summary.status = "completed"
            existing_summary.booking_ids = [item.booking_id for item in summary.items]

            await self._consultation_summary_store.save_summary(existing_summary)
            logger.info(
                f"Updated consultation summary {consultation_id} to status=completed "
                f"with {len(existing_summary.booking_ids)} bookings"
            )
            return True

        except Exception as e:
            logger.error(f"Error checking booking completion: {e}")
            return False
