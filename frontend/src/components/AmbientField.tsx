import { useEffect } from 'react';
import { useInsights } from '../api/hooks';
import { currentMonth } from '../lib/date';
import { dayMoodFromInsights } from '../lib/mood';

/**
 * The "living interface": a soft glow behind everything that reflects the user's
 * money weather — calm green on track, warm amber when stretched, a quiet ember
 * when over (never an alarm). Three cross-fading layers so a mood change melts in
 * rather than snapping. Reuses the cached insights query, so it costs no request.
 */
export function AmbientField() {
  const insights = useInsights(currentMonth());
  const mood = dayMoodFromInsights(insights.data);

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
