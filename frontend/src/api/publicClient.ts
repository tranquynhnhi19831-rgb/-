import axios from 'axios'

const isLocal = window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost'

export const publicApi = axios.create({
  // In production the reverse proxy serves the public API on the same origin.
  // Local development runs backend.public_main on port 8001.
  baseURL: isLocal ? 'http://127.0.0.1:8001' : window.location.origin
})
