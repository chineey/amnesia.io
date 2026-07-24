import { Bookmark } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { InspectorCard } from './InspectorCard';

function ProfileList({ title, items, accentClassName }) {
  if (!items?.length) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <h5 className={accentClassName + ' text-xs font-semibold'}>{title}</h5>
      <ul className="flex flex-col gap-1.5">
        {items.map((item, i) => (
          <li
            key={i}
            className="flex items-center justify-between gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 text-[13px]"
          >
            <span>{item.content}</span>
            <span className="shrink-0 rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {Math.round(item.confidence * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function CoreProfileCard({ coreProfile }) {
  const isEmpty = !coreProfile.facts?.length && !coreProfile.preferences?.length;

  return (
    <InspectorCard
      icon={<Bookmark className="size-4 text-violet-400" />}
      title="Core User Profile"
      badge={
        <Badge variant="outline" className="border-amber-400/20 bg-amber-400/10 text-amber-300">
          Always injected
        </Badge>
      }
    >
      {isEmpty ? (
        <p className="text-[13px] text-muted-foreground italic">
          No core profile extracted yet. End a session to trigger extraction.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <ProfileList title="Facts" items={coreProfile.facts} accentClassName="text-indigo-400" />
          <ProfileList title="Preferences" items={coreProfile.preferences} accentClassName="text-violet-400" />
        </div>
      )}
    </InspectorCard>
  );
}
