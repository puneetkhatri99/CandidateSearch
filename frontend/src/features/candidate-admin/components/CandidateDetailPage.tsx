import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { useCurrentUser } from '@/features/auth'
import { ApiError } from '@/shared/api/client'
import { Alert, Button, PageHeader } from '@/shared/ui'
import { useCandidate, useDeleteCandidate } from '../hooks'
import { CandidateEditForm } from './CandidateEditForm'
import { CandidateProfileView } from './CandidateProfileView'
import { DeleteCandidateDialog } from './DeleteCandidateDialog'

const backLink = (
  <Link to="/admin/candidates" className="w-fit rounded-xs text-sm text-accent-fg underline-offset-4 hover:underline">
    ← Back to candidates
  </Link>
)

export function CandidateDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { data: user } = useCurrentUser()
  const candidate = useCandidate(id)
  const deletion = useDeleteCandidate()
  const [searchParams] = useSearchParams()
  // The table's Edit action links here with ?edit=1 to open the form directly.
  const [editing, setEditing] = useState(searchParams.get('edit') === '1')
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  if (candidate.isPending) {
    return (
      <p role="status" className="text-sm text-fg-muted">
        Loading profile…
      </p>
    )
  }
  if (candidate.isError) {
    const notFound = candidate.error instanceof ApiError && [404, 422].includes(candidate.error.status)
    return (
      <div className="grid gap-4">
        {backLink}
        <Alert>{notFound ? 'This candidate does not exist or was deleted.' : candidate.error.message}</Alert>
      </div>
    )
  }

  const c = candidate.data
  const deleteError = deletion.error ? deletion.error.message || 'Could not delete. Please try again.' : null

  return (
    <div className="grid max-w-4xl grid-cols-[minmax(0,1fr)] gap-10">
      {backLink}
      <PageHeader
        title={c.full_name}
        description={c.headline}
        meta={`FILE ${c.id.slice(0, 8)}`}
        actions={
          !editing && (
            <>
              <Button variant="secondary" onClick={() => setEditing(true)}>
                Edit
              </Button>
              {user?.role === 'admin' && (
                <Button variant="danger" onClick={() => setConfirmingDelete(true)}>
                  Delete
                </Button>
              )}
            </>
          )
        }
      />

      {editing ? (
        <CandidateEditForm
          key={c.version}
          candidate={c}
          onSaved={() => setEditing(false)}
          onCancel={() => setEditing(false)}
          onReloadLatest={() => {
            setEditing(false)
            void candidate.refetch()
          }}
        />
      ) : (
        <CandidateProfileView candidate={c} />
      )}

      <DeleteCandidateDialog
        open={confirmingDelete}
        candidateName={c.full_name}
        pending={deletion.isPending}
        error={deleteError}
        onClose={() => {
          setConfirmingDelete(false)
          deletion.reset()
        }}
        onConfirm={() =>
          deletion.mutate(c.id, {
            onSuccess: () => navigate('/admin/candidates', { replace: true }),
          })
        }
      />
    </div>
  )
}
