import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuthStore } from '@/features/auth/store';

function getPasswordError(password: string): string | null {
  if (password.length < 8) return '密码长度至少 8 个字符';
  if (!/[a-zA-Z]/.test(password)) return '密码必须包含至少一个字母';
  if (!/\d/.test(password)) return '密码必须包含至少一个数字';
  return null;
}

export function RegisterPage() {
  const navigate = useNavigate();
  const registerFn = useAuthStore((s) => s.register);
  const loginFn = useAuthStore((s) => s.login);
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const passwordError = password ? getPasswordError(password) : null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    const pwErr = getPasswordError(password);
    if (pwErr) {
      setError(pwErr);
      return;
    }

    setSubmitting(true);
    try {
      await registerFn(email, password, displayName);
      // Auto-login after registration
      await loginFn(email, password);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : '注册失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-muted px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">注册</CardTitle>
          <CardDescription>创建你的学术调查账户</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="displayName">显示名称</Label>
              <Input
                id="displayName"
                type="text"
                placeholder="张三"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                placeholder="your@email.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              {passwordError && (
                <p className="text-sm text-amber-500">{passwordError}</p>
              )}
              {password && !passwordError && (
                <p className="text-sm text-green-500">密码强度合格</p>
              )}
            </div>
            {error && (
              <p className="text-sm text-red-500">{error}</p>
            )}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? '注册中...' : '注册'}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            已有账户？{' '}
            <Link to="/login" className="text-accent hover:underline">
              登录
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
