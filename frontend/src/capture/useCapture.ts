import { useContext } from 'react';
import { CaptureContext, type CaptureContextValue } from './CaptureContext';

export function useCapture(): CaptureContextValue {
  const ctx = useContext(CaptureContext);
  if (!ctx) throw new Error('useCapture must be used inside <Layout>');
  return ctx;
}
