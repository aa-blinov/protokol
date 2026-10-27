import { type ReactNode, useCallback, useEffect, useState } from "react";
import { getLocalModels, type LocalModelsState } from "./api";
import { FirstRun } from "./FirstRun";
import { Button } from "./ui";

/** Keeps the app behind the first-run screen until the models it needs are on disk. */
export function ModelGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LocalModelsState | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setFailure(null);
    getLocalModels()
      .then(setState)
      .catch((error: unknown) => setFailure(error instanceof Error ? error.message : String(error)));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (state?.ready) return <>{children}</>;
  if (state) return <FirstRun state={state} onRefresh={refresh} />;
  if (failure) {
    return (
      <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-4 px-6">
        <p role="alert" className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900">
          {failure}
        </p>
        <Button onClick={refresh}>Повторить</Button>
      </main>
    );
  }
  return null;
}
