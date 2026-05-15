import { Link, useNavigate } from 'react-router-dom';
import {
  BarChart3,
  BookOpen,
  GraduationCap,
  Library,
  LogOut,
  Ruler,
  Send,
  Shield,
  Sparkles,
  User,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useAuthStore } from '@/features/auth/store';

export function NavBar() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  // Read last visited survey ID from localStorage for analytics links
  const lastSurveyId = (() => {
    try {
      return localStorage.getItem('isp_last_survey_id');
    } catch {
      return null;
    }
  })();

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-surface">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        <div className="flex items-center gap-4">
          <Link to="/" className="flex items-center gap-2 font-semibold text-lg">
            <span className="text-accent">ISP</span>
            <span className="hidden sm:inline">学术调查平台</span>
          </Link>
          <Link
            to="/ai/generate"
            className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <Sparkles className="h-4 w-4" />
            <span className="hidden sm:inline">AI 生成</span>
          </Link>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground">
                <GraduationCap className="h-4 w-4" />
                <span className="hidden sm:inline">知识库</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-40">
              <DropdownMenuItem onClick={() => navigate('/kb/literature')}>
                <BookOpen className="mr-2 h-4 w-4" />
                文献检索
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate('/kb/scales')}>
                <Library className="mr-2 h-4 w-4" />
                量表库
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate('/kb/guides')}>
                <GraduationCap className="mr-2 h-4 w-4" />
                知识库
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          {lastSurveyId && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground">
                  <BarChart3 className="h-4 w-4" />
                  <span className="hidden sm:inline">分析</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-40">
                <DropdownMenuItem onClick={() => navigate(`/survey/${lastSurveyId}/analytics`)}>
                  <BarChart3 className="mr-2 h-4 w-4" />
                  数据质量
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => navigate(`/survey/${lastSurveyId}/measurement`)}>
                  <Ruler className="mr-2 h-4 w-4" />
                  测量工具箱
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => navigate(`/survey/${lastSurveyId}/analytics/ethics`)}>
                  <Shield className="mr-2 h-4 w-4" />
                  伦理合规
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => navigate(`/survey/${lastSurveyId}/distribution`)}>
                  <Send className="mr-2 h-4 w-4" />
                  样本发放
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="gap-2">
              <User className="h-4 w-4" />
              <span className="hidden sm:inline">{user?.display_name ?? '用户'}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuItem disabled className="text-xs text-muted-foreground">
              {user?.email}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={handleLogout} className="text-red-500">
              <LogOut className="mr-2 h-4 w-4" />
              退出登录
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
