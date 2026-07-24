import { useState, useCallback } from 'react';
import { streamEvalRun } from '@/lib/api';

export function useEvalRun({ userId, onSettled }) {
  const [logs, setLogs] = useState([]);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);

  const run = useCallback(async () => {
    setRunning(true);
    setLogs([]);
    setProgress(0);

    try {
      await streamEvalRun({ userId }, (event) => {
        if (event.type === 'log') {
          setLogs((prev) => [...prev, event.message]);
        } else if (event.type === 'progress') {
          setProgress(event.percent);
        } else if (event.type === 'result') {
          setLogs((prev) => [...prev, `Simulation Finished!\nAverage Personalization Score: ${event.avg_score}/10`]);
        }
      });
    } catch (err) {
      setLogs((prev) => [...prev, `[Error running simulation: ${err.message}]`]);
    } finally {
      setRunning(false);
      onSettled?.();
    }
  }, [userId, onSettled]);

  return { logs, running, progress, run };
}
