import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthGuard } from '@/features/auth/components/AuthGuard';
import { LoginPage } from '@/features/auth/components/LoginPage';
import { RegisterPage } from '@/features/auth/components/RegisterPage';
import { AppLayout } from '@/components/layout/AppLayout';
import { SurveyListPage } from './pages/SurveyListPage';
import { SurveyDesignerPage } from './pages/SurveyDesignerPage';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public routes */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />

        {/* Protected routes */}
        <Route
          element={
            <AuthGuard>
              <AppLayout />
            </AuthGuard>
          }
        >
          <Route path="/" element={<SurveyListPage />} />
          <Route path="/survey/:id" element={<SurveyDesignerPage />} />
          <Route path="/survey/new" element={<SurveyDesignerPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
