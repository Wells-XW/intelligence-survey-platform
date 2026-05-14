import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthGuard } from '@/features/auth/components/AuthGuard';
import { LoginPage } from '@/features/auth/components/LoginPage';
import { RegisterPage } from '@/features/auth/components/RegisterPage';
import { AppLayout } from '@/components/layout/AppLayout';
import { SurveyListPage } from './pages/SurveyListPage';
import { SurveyDesignerPage } from './pages/SurveyDesignerPage';
import { AnalyticsDashboardPage } from './pages/AnalyticsDashboardPage';
import { AiGenerationPage } from './pages/AiGenerationPage';
import { SurveyFillPage } from './pages/SurveyFillPage';
import LiteratureSearchPage from './pages/LiteratureSearchPage';
import ScaleLibraryPage from './pages/ScaleLibraryPage';
import KnowledgeBasePage from './pages/KnowledgeBasePage';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public routes */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        {/* Public survey fill page — no auth required */}
        <Route path="/survey/:id/fill" element={<SurveyFillPage />} />

        {/* Protected routes */}
        <Route
          element={
            <AuthGuard>
              <AppLayout />
            </AuthGuard>
          }
        >
          <Route path="/" element={<SurveyListPage />} />
          <Route path="/survey/new" element={<SurveyDesignerPage />} />
          <Route path="/survey/:id" element={<SurveyDesignerPage />} />
          <Route path="/survey/:id/analytics" element={<AnalyticsDashboardPage />} />
          <Route path="/ai/generate" element={<AiGenerationPage />} />
          <Route path="/kb/literature" element={<LiteratureSearchPage />} />
          <Route path="/kb/scales" element={<ScaleLibraryPage />} />
          <Route path="/kb/guides" element={<KnowledgeBasePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
