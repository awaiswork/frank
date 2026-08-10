import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { apiFetch, json } from '../api/client';
import { Button, Card } from '../components/ui';
import { Wordmark } from '../components/Logo';

/**
 * Turning weekly summaries off, from a link, with no session.
 *
 * The emailed URL points here rather than at the API, and this page performs nothing on
 * load: mail scanners and some clients fetch every link in a message, so a GET that
 * unsubscribed would fire without anyone reading the email. The button is the action.
 */
export function Unsubscribe() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [state, setState] = useState<'idle' | 'saving' | 'done' | 'error'>('idle');

  async function confirm() {
    setState('saving');
    try {
      // No session involved: the endpoint takes the signed token instead, so this
      // works from a device that has never signed in.
      await apiFetch<{ detail: string }>('/notifications/unsubscribe', {
        method: 'POST',
        body: json({ token }),
      });
      setState('done');
    } catch {
      setState('error');
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center px-4">
      <Card className="flex w-full max-w-[420px] flex-col gap-4 text-center">
        <div className="self-center">
          <Wordmark />
        </div>
        {state === 'done' ? (
          <>
            <h1 className="font-display text-[20px] font-semibold">That's off now</h1>
            {/* Says what did *not* happen too — an unsubscribe link that might have
                done something else to the account is a link people hesitate over. */}
            <p className="text-[14.5px] text-muted">
              No more weekly summaries. Nothing else about your account changed, and you can turn
              them back on in Settings whenever you like.
            </p>
          </>
        ) : (
          <>
            <h1 className="font-display text-[20px] font-semibold">Stop the weekly summaries?</h1>
            <p className="text-[14.5px] text-muted">
              You'll keep getting sign-in codes and anything else you actually asked for.
            </p>
            <Button onClick={confirm} disabled={!token || state === 'saving'}>
              {state === 'saving' ? 'Turning off…' : 'Turn them off'}
            </Button>
            {!token && (
              <p className="text-[13px] text-over">
                This link is missing its token — try the one in the email again.
              </p>
            )}
            {state === 'error' && (
              <p className="text-[13px] text-over">Couldn't reach Frankly — try again.</p>
            )}
          </>
        )}
      </Card>
    </main>
  );
}
