/**
 * "Remember Me" stores email only — never the password.
 * Passwords must not be written to localStorage (even encrypted), because
 * client-side keys are inspectable and ciphertext can be decrypted in-browser.
 */

const STORAGE_KEYS = {
  email: 'rememberedEmail',
  /** Legacy key — cleared on read so old ciphertext passwords are removed. */
  password: 'rememberedPassword',
  flag: 'rememberMe',
} as const;

export async function getRememberedCredentials(): Promise<{
  email: string;
  password: string;
} | null> {
  if (typeof window === 'undefined') return null;
  // Purge any historically stored password material.
  localStorage.removeItem(STORAGE_KEYS.password);
  const email = localStorage.getItem(STORAGE_KEYS.email);
  const flag = localStorage.getItem(STORAGE_KEYS.flag) === 'true';
  if (!email || !flag) return null;
  return { email, password: '' };
}

export async function setRememberedCredentials(
  email: string,
  _password?: string,
): Promise<void> {
  if (typeof window === 'undefined') return;
  localStorage.setItem(STORAGE_KEYS.email, email);
  localStorage.removeItem(STORAGE_KEYS.password);
  localStorage.setItem(STORAGE_KEYS.flag, 'true');
}

export function clearRememberedCredentials(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(STORAGE_KEYS.email);
  localStorage.removeItem(STORAGE_KEYS.password);
  localStorage.removeItem(STORAGE_KEYS.flag);
}

export function hasRememberedCredentials(): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem(STORAGE_KEYS.flag) === 'true';
}
