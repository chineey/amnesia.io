import { useEffect, useRef } from 'react';
import { Cpu, MessageSquare, RefreshCw, Send, Sparkles } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { MessageBubble } from './MessageBubble';
import { cn } from '@/lib/utils';

export function ChatPanel({
  messages,
  isStreaming,
  inputText,
  setInputText,
  onSend,
  sessionId,
  className,
}) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = (e) => {
    e.preventDefault();
    onSend(inputText);
    setInputText('');
  };

  return (
    <Card className={cn('glass flex h-full flex-col gap-0 overflow-hidden py-0', className)}>
      <div className="flex shrink-0 items-center justify-between border-b border-border px-5 py-4">
        <div className="flex items-center gap-2.5">
          <MessageSquare className="size-4.5 text-primary" />
          <h3 className="font-heading text-sm font-semibold">Active Turn Stream</h3>
          <span className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
            {sessionId.slice(0, 8)}…
          </span>
        </div>
        <div className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex">
          <Sparkles className="size-3.5 text-cyan-400" />
          <span>Context updates session-by-session</span>
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-5 p-5">
          {messages.length === 0 ? (
            <div className="flex h-[50vh] flex-col items-center justify-center text-center text-muted-foreground">
              <Cpu className="mb-4 size-11 opacity-40" />
              <h4 className="font-heading text-base font-medium text-foreground">
                Start a conversation with amnesia.io
              </h4>
              <p className="mt-2 max-w-[360px] text-sm">
                Introduce yourself, declare some preferences, and tell amnesia.io about your
                current projects. Then click <b className="text-foreground">End Session</b> to
                watch it build your Core Profile!
              </p>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <MessageBubble
                key={idx}
                role={msg.role}
                content={msg.content}
                isTyping={isStreaming && idx === messages.length - 1}
              />
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      <form onSubmit={handleSubmit} className="flex shrink-0 gap-3 border-t border-border bg-black/15 p-4">
        <Input
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          placeholder="Tell amnesia.io your preferences or build profile…"
          disabled={isStreaming}
          className="h-11 rounded-xl px-4"
        />
        <Button
          type="submit"
          disabled={isStreaming || !inputText.trim()}
          className="h-11 gap-1.5 rounded-xl bg-gradient-to-br from-indigo-500 to-primary px-5"
        >
          {isStreaming ? <RefreshCw className="size-4 animate-spin" /> : <Send className="size-4" />}
          <span>Send</span>
        </Button>
      </form>
    </Card>
  );
}
