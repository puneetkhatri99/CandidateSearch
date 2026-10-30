// No look-alike characters (0/O, 1/l/I), because an admin reads this out or pastes it to someone.
const ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
export const GENERATED_PASSWORD_LENGTH = 16
// Bytes at or above this would favour the first characters; they are skipped.
const UNBIASED_LIMIT = 256 - (256 % ALPHABET.length)

/** A random temporary password from the browser's cryptographic generator. */
export function generateTemporaryPassword(): string {
  let password = ''
  while (password.length < GENERATED_PASSWORD_LENGTH) {
    const bytes = crypto.getRandomValues(new Uint8Array(GENERATED_PASSWORD_LENGTH * 2))
    for (const byte of bytes) {
      if (byte < UNBIASED_LIMIT && password.length < GENERATED_PASSWORD_LENGTH) {
        password += ALPHABET[byte % ALPHABET.length]
      }
    }
  }
  return password
}
