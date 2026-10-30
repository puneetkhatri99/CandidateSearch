/** Only same-site paths are allowed as a post-login redirect (no open redirects). */
export function safeNextPath(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/\\') ? next : '/admin/candidates'
}
