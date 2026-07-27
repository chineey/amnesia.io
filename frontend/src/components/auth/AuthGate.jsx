import { useState } from 'react';
import { Brain, Check, Copy, KeyRound } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { signup, login, setToken } from '@/lib/auth';

function ApiKeyReveal({ apiKey, onContinue }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(apiKey);
    setCopied(true);
    toast.success('API key copied to clipboard.');
  };

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <div className="flex size-9 items-center justify-center rounded-full border border-emerald-400/20 bg-emerald-400/10">
          <KeyRound className="size-4.5 text-emerald-400" />
        </div>
        <CardTitle className="mt-3">Your GenPost API key</CardTitle>
        <CardDescription>
          Paste this into GenPost's Settings → Connect Amnesia to link your account. It's shown
          only once — if you lose it, you can generate a new one from Amnesia later.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-black/20 px-3 py-2 font-mono text-xs break-all text-foreground">
          {apiKey}
        </div>
        <Button onClick={handleCopy} variant="outline" className="gap-1.5">
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? 'Copied' : 'Copy key'}
        </Button>
        <Button onClick={onContinue} className="bg-gradient-to-br from-primary to-indigo-400 text-primary-foreground">
          Continue to Amnesia
        </Button>
      </CardContent>
    </Card>
  );
}

export function AuthGate({ onAuthenticated }) {
  const [mode, setMode] = useState('login'); // 'login' | 'signup'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [revealedApiKey, setRevealedApiKey] = useState(null);
  const [pendingToken, setPendingToken] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      if (mode === 'signup') {
        const data = await signup(email, password);
        setPendingToken(data.token);
        setRevealedApiKey(data.api_key);
      } else {
        const data = await login(email, password);
        setToken(data.token);
        onAuthenticated();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (revealedApiKey) {
    return (
      <div className="flex h-screen items-center justify-center p-4">
        <ApiKeyReveal
          apiKey={revealedApiKey}
          onContinue={() => {
            setToken(pendingToken);
            onAuthenticated();
          }}
        />
      </div>
    );
  }

  return (
    <div className="flex h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <div className="flex size-9 items-center justify-center rounded-full border border-cyan-400/20 bg-cyan-400/10">
            <Brain className="size-4.5 text-cyan-400" />
          </div>
          <CardTitle className="mt-3">
            {mode === 'login' ? 'Log in to amnesia.io' : 'Create your amnesia.io account'}
          </CardTitle>
          <CardDescription>
            {mode === 'login'
              ? 'Access your memory profile and chat playground.'
              : 'Sign up to get an API key you can connect to GenPost.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted-foreground" htmlFor="email">Email</label>
              <Input
                id="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-muted-foreground" htmlFor="password">Password</label>
              <Input
                id="password"
                type="password"
                required
                minLength={8}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            {error && <p className="text-xs text-destructive">{error}</p>}

            <Button
              type="submit"
              disabled={submitting}
              className="mt-1 bg-gradient-to-br from-primary to-indigo-400 text-primary-foreground"
            >
              {submitting ? 'Please wait…' : mode === 'login' ? 'Log in' : 'Sign up'}
            </Button>

            <button
              type="button"
              onClick={() => {
                setMode(mode === 'login' ? 'signup' : 'login');
                setError('');
              }}
              className="text-center text-xs text-muted-foreground hover:text-foreground"
            >
              {mode === 'login' ? "Don't have an account? Sign up" : 'Already have an account? Log in'}
            </button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
