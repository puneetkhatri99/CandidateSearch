import { createBrowserRouter } from 'react-router'
import { AiSpendPage } from '@/features/ai-usage'
import { ChangePasswordPage, LoginPage, RequireAuth, RequireRole } from '@/features/auth'
import { CandidateCreatePage, CandidateDetailPage, CandidateSearchPage } from '@/features/candidate-admin'
import { CandidateIntakePage, PrivacyNoticePage } from '@/features/candidate-intake'
import { JobCreatePage, JobDetailPage, JobListPage } from '@/features/jobs'
import { UserListPage } from '@/features/user-admin'
import { HomePage, NotFoundPage } from './pages'
import { PublicLayout, RootLayout } from './RootLayout'

const routes = [
  {
    element: <PublicLayout />,
    children: [
      { path: '/', element: <HomePage /> },
      { path: '/apply', element: <CandidateIntakePage /> },
      { path: '/privacy', element: <PrivacyNoticePage /> },
      { path: '/login', element: <LoginPage /> },
    ],
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <PublicLayout />,
        children: [{ path: '/account/password', element: <ChangePasswordPage /> }],
      },
      {
        element: <RootLayout />,
        children: [
          { path: '/admin/ai-usage', element: <AiSpendPage /> },
          { path: '/admin/candidates', element: <CandidateSearchPage /> },
          { path: '/admin/candidates/new', element: <CandidateCreatePage /> },
          { path: '/admin/candidates/:id', element: <CandidateDetailPage /> },
          { path: '/jobs', element: <JobListPage /> },
          { path: '/jobs/new', element: <JobCreatePage /> },
          { path: '/jobs/:id', element: <JobDetailPage /> },
          {
            element: <RequireRole role="admin" />,
            children: [{ path: '/admin/users', element: <UserListPage /> }],
          },
        ],
      },
    ],
  },
  {
    element: <PublicLayout />,
    children: [{ path: '*', element: <NotFoundPage /> }],
  },
]

export const router = createBrowserRouter(routes)
