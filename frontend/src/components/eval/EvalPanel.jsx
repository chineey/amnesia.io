import { Cpu, Layers, Play } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';

export function EvalPanel({ logs, running, progress, onRun }) {
  return (
    <Card className="glass col-span-1 flex h-full flex-col gap-6 overflow-hidden p-6 md:col-span-2">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-center gap-3">
          <Layers className="size-6 text-primary" />
          <div>
            <h3 className="font-heading text-base font-semibold">Evaluation &amp; Simulation Harness</h3>
            <p className="text-[13px] text-muted-foreground">
              Simulate a synthetic user journey across 5 sessions to measure personalization
              quality and memory decay.
            </p>
          </div>
        </div>

        <Button
          onClick={onRun}
          disabled={running}
          className="shrink-0 gap-2 rounded-xl bg-gradient-to-br from-primary to-indigo-400 px-5 py-2.5"
        >
          <Play className="size-4" />
          <span>{running ? 'Running Simulation…' : 'Run 5-Session Simulation'}</span>
        </Button>
      </div>

      {running && <Progress value={progress} />}

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-[#040711]">
        <div className="flex shrink-0 items-center gap-1.5 border-b border-border bg-black/30 px-4 py-2.5">
          <span className="size-2.5 rounded-full bg-red-400" />
          <span className="size-2.5 rounded-full bg-amber-400" />
          <span className="size-2.5 rounded-full bg-emerald-400" />
          <span className="ml-3 font-mono text-[11px] text-muted-foreground">amnesia.io Simulation Logs</span>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-1.5 p-4 font-mono text-xs text-emerald-400">
            {logs.length === 0 ? (
              <div className="flex h-[40vh] flex-col items-center justify-center text-center text-muted-foreground">
                <Cpu className="mb-3 size-10 opacity-40" />
                <span>Waiting to run synthetic simulation. Click the button above to begin.</span>
              </div>
            ) : (
              logs.map((log, i) => (
                <pre key={i} className="border-b border-dashed border-emerald-400/5 pb-1 whitespace-pre-wrap">
                  {log}
                </pre>
              ))
            )}
          </div>
        </ScrollArea>
      </div>
    </Card>
  );
}
