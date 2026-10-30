/** Placeholder text. Replace with legally reviewed wording and bump PRIVACY_NOTICE_VERSION on the backend. */
export function PrivacyNoticePage() {
  return (
    <article className="space-y-4 text-base text-fg-muted">
      <p className="rounded-md bg-surface-muted px-4 py-3 text-sm text-fg-muted">
        Draft notice (version 2026-10-draft). Must be replaced before launch.
      </p>
      <h1 className="text-3xl font-semibold tracking-tight text-fg">Candidate privacy notice</h1>
      <p className="max-w-prose">
        We store the profile you submit (contact details, work history, education, skills and preferences) to match you
        with job roles and so recruiters can contact you about relevant opportunities.
      </p>
      <p className="max-w-prose">
        We do not collect your date of birth, gender or photo, and we do not use your name or contact details when
        matching you to roles.
      </p>
      <p className="max-w-prose">
        Your expected salary is optional. If you give it, it is compared with a role&apos;s pay range when ranking
        candidates, which means it is sent, without your name or contact details, to our AI provider (OpenAI).
      </p>
      <p className="max-w-prose">You can ask us at any time to see, correct or delete your data.</p>
    </article>
  )
}
