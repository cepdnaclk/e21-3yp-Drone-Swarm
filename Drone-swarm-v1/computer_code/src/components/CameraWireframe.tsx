// CameraWireframe: draws a wireframe pyramid representing a calibrated USB
// camera in the 3D scene. Accepts the camera pose in WORLD coordinates as
// emitted by the Python backend's Tracker.camera_poses_in_world():
//   R = camera-axes-in-world (3x3, orthonormal, OpenCV convention: +z forward,
//                              +x right, +y down)
//   t = camera center in world, metres
// We render in three.js Y-up via a -90° rotation about X:
// (wx, wy, wz) -> (wx, wz, -wy). A bare Y/Z swap flips handedness and
// visually mirrors the Y axis.

import { BufferAttribute, BufferGeometry, EdgesGeometry, LineBasicMaterial } from "three";

export default function CameraWireframe({ R, t }: { R: number[][], t: number[] }) {
  // Camera-local pyramid: apex at origin, base square 1 unit "forward".
  // Scaled small so the wireframe doesn't dominate the scene.
  const scale = 0.05;
  const local = [
    [0, 0, 0],
    [ 1,  0.85, 1],
    [-1,  0.85, 1],
    [-1, -0.85, 1],
    [ 1, -0.85, 1],
  ];
  const indices = [0, 1, 2, 0, 2, 3, 0, 3, 4, 0, 4, 1];

  const transformed = new Float32Array(
    local.flatMap((v) => {
      const sx = v[0] * scale;
      const sy = v[1] * scale;
      const sz = v[2] * scale;
      const wx = R[0][0] * sx + R[0][1] * sy + R[0][2] * sz + t[0];
      const wy = R[1][0] * sx + R[1][1] * sy + R[1][2] * sz + t[1];
      const wz = R[2][0] * sx + R[2][1] * sy + R[2][2] * sz + t[2];
      // three.js: Y is up; world has Z up. Rotate -90° about X.
      return [wx, wz, -wy];
    })
  );

  const geometry = new BufferGeometry();
  geometry.setIndex(indices);
  geometry.setAttribute("position", new BufferAttribute(transformed, 3));

  const wireframeGeo = new EdgesGeometry(geometry);
  const mat = new LineBasicMaterial({ color: 0x000000, linewidth: 2 });

  return (
    <mesh>
      <lineSegments args={[wireframeGeo, mat]} />
    </mesh>
  );
}
