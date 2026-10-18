/** Flat finding environment keys shared by intake and exact-pin recall. */
export const MEMORY_ENV_KEYS = ['runtime', 'runtime_version', 'robot', 'controller', 'observation', 'os', 'python', 'architecture', 'sim_backend', 'render_backend'];
const PACKAGE_KEY = /^package\.[A-Za-z_][A-Za-z0-9_]{0,79}$/;

export function memoryEnvironmentKey(key: string): boolean {
  return MEMORY_ENV_KEYS.includes(key) || PACKAGE_KEY.test(key);
}
