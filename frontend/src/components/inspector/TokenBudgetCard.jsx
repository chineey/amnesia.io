import { Cpu } from 'lucide-react';
import { InspectorCard } from './InspectorCard';
import { cn } from '@/lib/utils';

function StatRow({ label, value, strong }) {
  return (
    <div className="flex justify-between text-xs text-muted-foreground">
      <span>{label}</span>
      <span className={cn(strong && 'font-semibold text-foreground')}>{value}</span>
    </div>
  );
}

export function TokenBudgetCard({ tokenStats }) {
  return (
    <InspectorCard icon={<Cpu className="size-4 text-emerald-400" />} title="Token Cap Enforcement">
      {!tokenStats ? (
        <p className="text-[13px] text-muted-foreground italic">
          Send a message to view token allocation stats.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="h-2 overflow-hidden rounded-full bg-white/5">
            <div
              className={cn(
                'h-full rounded-full transition-all duration-500',
                tokenStats.total_used > 700 ? 'bg-destructive' : 'bg-emerald-400'
              )}
              style={{ width: `${(tokenStats.total_used / tokenStats.total_cap) * 100}%` }}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <StatRow label="Total Context Limit" value={`${tokenStats.total_cap} tokens`} strong />
            <StatRow label="Core Profile Injected" value={`${tokenStats.profile_tokens} tokens`} />
            <StatRow label="Redis History Tail" value={`${tokenStats.working_memory_injected} tokens`} />
            <StatRow label="Semantic Episodic Injected" value={`${tokenStats.episodic_tokens} tokens`} />
            <StatRow label="Remaining Budget" value={`${tokenStats.remaining_tokens} tokens`} strong />
          </div>
        </div>
      )}
    </InspectorCard>
  );
}
