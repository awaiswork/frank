import { useEffect } from 'react';
import { useDailyNote } from '../api/hooks';

/**
 * The "living interface": a soft glow behind everything that reflects the user's
 * money weather — calm green on track, warm amber when stretched, a quiet ember
 * when over (never an alarm). Three cross-fading layers so a mood change melts in
 * rather than snapping.
 *
 * Reads the same server mood as Frankly's note, so the glow and the chip can never
 * disagree. The daily query is invalidated on every money write, so this still
 * shifts the moment you log something.
 */
export function AmbientField() {
  const daily = useDailyNote();
  const mood = daily.data?.mood ?? 'unknown';

  useEffect(() => {
    document.documentElement.setAttribute('data-mood', mood);
  }, [mood]);

  return (
    <div className="ambient" aria-hidden="true">
      <div className="ambient__layer ambient__go" />
      <div className="ambient__layer ambient__wait" />
      <div className="ambient__layer ambient__over" />
    </div>
  );
}
