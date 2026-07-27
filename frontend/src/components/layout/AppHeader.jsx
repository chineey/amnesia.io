import { useState } from 'react';
import { toast } from 'sonner';
import { Brain, Check, Copy, KeyRound, LogOut, MessageSquare, Layers, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { regenerateApiKey } from '@/lib/auth';

function ConnectGenPostDialog({ apiKeyPrefix }) {
  const [open, setOpen] = useState(false);
  const [newKey, setNewKey] = useState(null);
  const [regenerating, setRegenerating] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      const data = await regenerateApiKey();
      setNewKey(data.api_key);
      setCopied(false);
    } catch (err) {
      toast.error(`Failed to regenerate key: ${err.message}`);
    } finally {
      setRegenerating(false);
    }
  };

  const handleCopy = async () => {
    await navigator.clipboard.writeText(newKey);
    setCopied(true);
  };

  return (
    <AlertDialog open={open} onOpenChange={(next) => { setOpen(next); if (!next) setNewKey(null); }}>
      <AlertDialogTrigger
        render={
          <Button variant="outline" className="gap-1.5">
            <KeyRound className="size-3.5" />
            <span className="hidden sm:inline">Connect GenPost</span>
          </Button>
        }
      />
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Connect to GenPost</AlertDialogTitle>
          <AlertDialogDescription>
            {newKey ? (
              <>
                Your new API key (shown once — copy it now):
                <div className="mt-3 flex items-center gap-2 rounded-lg border border-border bg-black/20 px-3 py-2 font-mono text-xs break-all text-foreground">
                  {newKey}
                </div>
              </>
            ) : (
              <>
                Paste your API key into GenPost's Settings → Connect Amnesia.
                {apiKeyPrefix && <> Your current key ends in <span className="font-mono text-foreground">…{apiKeyPrefix}</span>.</>}
                {' '}Lost it? Generate a new one below (this invalidates the old one).
              </>
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Close</AlertDialogCancel>
          {newKey ? (
            <AlertDialogAction onClick={handleCopy} className="gap-1.5">
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              {copied ? 'Copied' : 'Copy key'}
            </AlertDialogAction>
          ) : (
            <AlertDialogAction onClick={handleRegenerate} disabled={regenerating}>
              {regenerating ? 'Generating…' : 'Generate new key'}
            </AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function AppHeader({ authUser, sessionCount, onEndSession, onPurgeMemories, onLogout }) {
  const [endOpen, setEndOpen] = useState(false);
  const [purgeOpen, setPurgeOpen] = useState(false);
  const [ending, setEnding] = useState(false);
  const [purging, setPurging] = useState(false);

  const handleEndSession = async () => {
    setEnding(true);
    try {
      await onEndSession();
      toast.success("Session teardown triggered — your Core Profile will update in a few seconds.");
    } catch (err) {
      toast.error(`Failed to end session: ${err.message}`);
    } finally {
      setEnding(false);
      setEndOpen(false);
    }
  };

  const handlePurge = async () => {
    setPurging(true);
    try {
      await onPurgeMemories();
      toast.success('All memories purged.');
    } catch (err) {
      toast.error(`Purge failed: ${err.message}`);
    } finally {
      setPurging(false);
      setPurgeOpen(false);
    }
  };

  return (
    <header className="glass flex h-auto flex-col gap-3 rounded-2xl px-4 py-3 sm:h-[70px] sm:flex-row sm:items-center sm:justify-between sm:px-6">
      <div className="flex items-center gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-full border border-cyan-400/20 bg-cyan-400/10">
          <Brain className="size-4.5 text-cyan-400" />
        </div>
        <div>
          <h1 className="flex items-center gap-2 font-heading text-lg font-bold text-foreground">
            amnesia.io
            <Badge className="bg-gradient-to-br from-primary to-indigo-400 text-[10px] font-bold">
              MemoryAgent
            </Badge>
          </h1>
          <p className="text-[11px] text-muted-foreground">Powered by Groq &amp; Gemini, backed by Neon + Redis</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 sm:gap-3">
        <div className="hidden items-center gap-2 rounded-full border border-border bg-black/20 px-3 py-1.5 text-xs text-muted-foreground md:flex">
          <span className="relative flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex size-2 rounded-full bg-emerald-400" />
          </span>
          Live
        </div>

        <TabsList>
          <TabsTrigger value="chat" className="gap-1.5">
            <MessageSquare className="size-3.5" />
            <span className="hidden sm:inline">Chat Playground</span>
            <span className="sm:hidden">Chat</span>
          </TabsTrigger>
          <TabsTrigger value="eval" className="gap-1.5">
            <Layers className="size-3.5" />
            <span className="hidden sm:inline">Evaluation Harness</span>
            <span className="sm:hidden">Eval</span>
          </TabsTrigger>
        </TabsList>

        <ConnectGenPostDialog apiKeyPrefix={authUser?.api_key_prefix} />

        <Button variant="ghost" onClick={onLogout} className="gap-1.5">
          <LogOut className="size-3.5" />
          <span className="hidden sm:inline">Log out</span>
        </Button>

        <AlertDialog open={endOpen} onOpenChange={setEndOpen}>
          <AlertDialogTrigger
            render={
              <Button className="gap-1.5 bg-gradient-to-br from-primary to-blue-500 text-primary-foreground">
                <LogOut className="size-3.5" />
                <span>End Session {sessionCount}</span>
              </Button>
            }
          />
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>End current session?</AlertDialogTitle>
              <AlertDialogDescription>
                This runs the extraction &amp; contradiction-resolution pass to update your Core
                Profile, then clears active working memory and starts a new session.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={ending}>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={handleEndSession} disabled={ending}>
                {ending ? 'Ending…' : 'End Session'}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        <AlertDialog open={purgeOpen} onOpenChange={setPurgeOpen}>
          <AlertDialogTrigger
            render={
              <Button variant="destructive" className="gap-1.5">
                <Trash2 className="size-3.5" />
                <span className="hidden sm:inline">Purge Memory</span>
              </Button>
            }
          />
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Purge all memory?</AlertDialogTitle>
              <AlertDialogDescription>
                This permanently deletes every Core Profile entry and episodic memory stored for
                this user. This cannot be undone.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={purging}>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={handlePurge}
                disabled={purging}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/80"
              >
                {purging ? 'Purging…' : 'Purge Everything'}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </header>
  );
}
