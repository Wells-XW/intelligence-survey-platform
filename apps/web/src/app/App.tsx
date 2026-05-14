import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { SurveyListPage } from './pages/SurveyListPage';
import { SurveyDesignerPage } from './pages/SurveyDesignerPage';

export function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-surface-muted">
        <Routes>
          <Route path="/" element={<SurveyListPage />} />
          <Route path="/survey/:id" element={<SurveyDesignerPage />} />
          <Route path="/survey/new" element={<SurveyDesignerPage />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
