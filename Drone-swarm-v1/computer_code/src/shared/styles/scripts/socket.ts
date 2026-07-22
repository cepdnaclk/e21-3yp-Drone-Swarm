import { io } from 'socket.io-client';
import { BACKEND_URL } from './config';

// Empty BACKEND_URL connects Socket.IO to the same origin that served the page
// (production, and dev via the Vite proxy). Set VITE_BACKEND_URL to override.
export const socket = io(BACKEND_URL);
