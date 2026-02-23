import React, { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

// Augment JSX namespace to support React Three Fiber elements
declare global {
  namespace JSX {
    interface IntrinsicElements {
      group: any;
      ambientLight: any;
      pointLight: any;
      mesh: any;
      planeGeometry: any;
      meshStandardMaterial: any;
      boxGeometry: any;
      sphereGeometry: any;
      meshBasicMaterial: any;
      directionalLight: any;
      cylinderGeometry: any;
      coneGeometry: any;
      color: any;
      fog: any;
    }
  }
}

// Augment React module to support newer TS/React resolution for IntrinsicElements
declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      group: any;
      ambientLight: any;
      pointLight: any;
      mesh: any;
      planeGeometry: any;
      meshStandardMaterial: any;
      boxGeometry: any;
      sphereGeometry: any;
      meshBasicMaterial: any;
      directionalLight: any;
      cylinderGeometry: any;
      coneGeometry: any;
      color: any;
      fog: any;
    }
  }
}

export type SceneTheme = 'default' | 'city' | 'beach' | 'ancient';

// --- Components for each theme ---

const CityScene = () => {
  const groupRef = useRef<THREE.Group>(null);
  
  // Generate random buildings
  const buildings = useMemo(() => {
    const items = [];
    for (let i = 0; i < 40; i++) {
      const height = Math.random() * 3 + 0.5;
      const position = [
        (Math.random() - 0.5) * 15,
        height / 2,
        (Math.random() - 0.5) * 15
      ];
      const isPurp = Math.random() > 0.8;
      items.push({ position, height, isPurp });
    }
    return items;
  }, []);

  useFrame((state) => {
    if (groupRef.current) {
      groupRef.current.rotation.y += 0.002;
    }
  });

  return (
    <group ref={groupRef}>
      <ambientLight intensity={0.5} color="#4c1d95" />
      <pointLight position={[10, 10, 10]} intensity={1.5} color="#c026d3" />
      <pointLight position={[-10, 5, -10]} intensity={1.5} color="#3b82f6" />
      
      {/* Floor */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
        <planeGeometry args={[50, 50]} />
        <meshStandardMaterial color="#0f172a" roughness={0.2} metalness={0.8} />
      </mesh>

      {/* Buildings */}
      {buildings.map((b, i) => (
        <mesh key={i} position={b.position as [number, number, number]}>
          <boxGeometry args={[0.8, b.height, 0.8]} />
          <meshStandardMaterial 
            color={b.isPurp ? "#4c1d95" : "#1e293b"} 
            emissive={Math.random() > 0.7 ? "#c026d3" : "#000"}
            emissiveIntensity={2}
          />
        </mesh>
      ))}
      
      {/* Car lights (moving spheres) */}
      <CarLights />
    </group>
  );
};

const CarLights = () => {
  const carsRef = useRef<THREE.Group>(null);
  
  const cars = useMemo(() => {
    return [...Array(20)].map((_, i) => ({
      pos: [(Math.random() - 0.5) * 12, 0.1, (Math.random() - 0.5) * 12] as [number, number, number],
      color: i % 2 === 0 ? "#f87171" : "#fbbf24"
    }));
  }, []);

  useFrame(() => {
    if (carsRef.current) {
      carsRef.current.rotation.y -= 0.005;
    }
  });

  return (
    <group ref={carsRef}>
       {cars.map((car, i) => (
         <mesh key={i} position={car.pos}>
           <sphereGeometry args={[0.05, 8, 8]} />
           <meshBasicMaterial color={car.color} />
         </mesh>
       ))}
    </group>
  );
};

const BeachScene = () => {
  const groupRef = useRef<THREE.Group>(null);

  const trees = useMemo(() => {
    return [...Array(5)].map((_, i) => {
      const angle = (i / 5) * Math.PI * 2;
      const r = 3 + Math.random();
      const x = Math.cos(angle) * r;
      const z = Math.sin(angle) * r;
      return { x, z, rot: Math.random() * Math.PI };
    });
  }, []);

  useFrame((state) => {
    if (groupRef.current) {
      groupRef.current.rotation.y += 0.001;
      // Gentle bobbing
      groupRef.current.position.y = Math.sin(state.clock.elapsedTime * 0.5) * 0.1;
    }
  });

  return (
    <group ref={groupRef}>
      <ambientLight intensity={0.8} color="#fff7ed" />
      <directionalLight position={[5, 10, 5]} intensity={2} color="#fef3c7" />
      
      {/* Ocean */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.2, 0]}>
        <planeGeometry args={[50, 50]} />
        <meshStandardMaterial color="#06b6d4" roughness={0.2} metalness={0.1} transparent opacity={0.8} />
      </mesh>

      {/* Sand Island */}
      <mesh position={[0, -0.1, 0]}>
        <cylinderGeometry args={[6, 7, 1, 32]} />
        <meshStandardMaterial color="#fde68a" />
      </mesh>

      {/* Trees */}
      {trees.map((t, i) => (
          <group key={i} position={[t.x, 0.4, t.z]} rotation={[0.1, t.rot, 0.1]}>
             {/* Trunk */}
             <mesh position={[0, 1, 0]}>
               <cylinderGeometry args={[0.1, 0.2, 2, 8]} />
               <meshStandardMaterial color="#78350f" />
             </mesh>
             {/* Leaves */}
             <mesh position={[0, 2, 0]}>
               <coneGeometry args={[1.2, 1.5, 8]} />
               <meshStandardMaterial color="#15803d" />
             </mesh>
             <mesh position={[0, 2.5, 0]}>
               <coneGeometry args={[1, 1.5, 8]} />
               <meshStandardMaterial color="#22c55e" />
             </mesh>
          </group>
      ))}
    </group>
  );
};

const AncientScene = () => {
  const groupRef = useRef<THREE.Group>(null);

  const { lanterns, mountains } = useMemo(() => {
    const l = [...Array(8)].map((_, i) => {
        const angle = (i / 8) * Math.PI * 2;
        const r = 5;
        return { x: Math.cos(angle)*r, z: Math.sin(angle)*r };
    });
    
    const m = [...Array(10)].map((_, i) => {
        const angle = (i / 10) * Math.PI * 2;
        const r = 10 + Math.random() * 5;
        return { x: Math.cos(angle)*r, z: Math.sin(angle)*r, height: 4 + Math.random()*4 };
    });
    return { lanterns: l, mountains: m };
  }, []);

  useFrame((state) => {
    if (groupRef.current) {
      groupRef.current.rotation.y += 0.0015;
    }
  });

  return (
    <group ref={groupRef}>
      <ambientLight intensity={0.5} color="#e4e4e7" />
      <directionalLight position={[-5, 5, 5]} intensity={1} color="#fff" />
      
      {/* Ground */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
        <planeGeometry args={[50, 50]} />
        <meshStandardMaterial color="#d4d4d8" />
      </mesh>

      {/* Central Pagoda */}
      <group position={[0, 0, 0]}>
        {/* Base */}
        <mesh position={[0, 0.5, 0]}>
           <boxGeometry args={[2, 1, 2]} />
           <meshStandardMaterial color="#52525b" />
        </mesh>
        {/* Tiers */}
        {[0, 1, 2].map(level => (
          <group key={level} position={[0, 1.5 + level * 1.5, 0]}>
            <mesh>
               <boxGeometry args={[1.2 - level*0.2, 1, 1.2 - level*0.2]} />
               <meshStandardMaterial color="#27272a" />
            </mesh>
            <mesh position={[0, 0.5, 0]}>
               <coneGeometry args={[2.5 - level*0.5, 1, 4]} />
               <meshStandardMaterial color="#18181b" />
            </mesh>
          </group>
        ))}
      </group>

      {/* Surrounding small lanterns/stones */}
      {lanterns.map((l, i) => (
         <mesh key={i} position={[l.x, 0.5, l.z]}>
            <boxGeometry args={[0.4, 1, 0.4]} />
            <meshStandardMaterial color="#52525b" />
         </mesh>
      ))}

      {/* Abstract Mountains in background */}
      {mountains.map((m, i) => (
          <mesh key={i} position={[m.x, 0, m.z]}>
              <coneGeometry args={[2, m.height, 4]} />
              <meshStandardMaterial color="#52525b" />
          </mesh>
      ))}
    </group>
  );
};

interface Scene3DProps {
  theme: SceneTheme;
}

export const Scene3D: React.FC<Scene3DProps> = ({ theme }) => {
  
  const bgColors = {
    'city': '#050510',
    'beach': '#bfdbfe',
    'ancient': '#e4e4e7',
    'default': 'transparent'
  };

  if (theme === 'default') return null;

  return (
    <div className="absolute inset-0 z-0 transition-opacity duration-1000 ease-in-out">
      <Canvas camera={{ position: [0, 4, 10], fov: 45 }}>
        <color attach="background" args={[bgColors[theme]]} />
        
        {theme === 'city' && <fog attach="fog" args={['#050510', 5, 25]} />}
        {theme === 'beach' && <fog attach="fog" args={['#bfdbfe', 5, 30]} />}
        {theme === 'ancient' && <fog attach="fog" args={['#e4e4e7', 2, 15]} />}

        {theme === 'city' && <CityScene />}
        {theme === 'beach' && <BeachScene />}
        {theme === 'ancient' && <AncientScene />}
      </Canvas>
    </div>
  );
};