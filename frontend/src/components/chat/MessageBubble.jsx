import { Sparkles, User } from 'lucide-react';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { cn } from '@/lib/utils';

export function MessageBubble({ role, content, isTyping }) {
  const isUser = role === 'user';

  return (
    <div className={cn('flex animate-slide-up items-start gap-3', isUser && 'flex-row-reverse')}>
      <Avatar className="mt-0.5 size-7 shrink-0">
        <AvatarFallback
          className={cn(isUser ? 'bg-secondary text-secondary-foreground' : 'bg-primary/15 text-primary')}
        >
          {isUser ? <User className="size-3.5" /> : <Sparkles className="size-3.5" />}
        </AvatarFallback>
      </Avatar>
      <div
        className={cn(
          'max-w-[80%] rounded-2xl border px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap',
          isUser
            ? 'rounded-tr-sm border-white/5 bg-secondary text-secondary-foreground'
            : 'rounded-tl-sm border-border bg-card/60 text-foreground'
        )}
      >
        {content || (isTyping ? <span className="text-muted-foreground italic">Typing…</span> : null)}
      </div>
    </div>
  );
}
