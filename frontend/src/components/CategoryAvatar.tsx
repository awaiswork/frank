import { categoryColor, categoryTint } from '../lib/categoryColor';

/** A rounded-square initial chip tinted to the category colour (design §lists). */
export function CategoryAvatar({
  initial,
  category,
  size = 38,
}: {
  initial: string;
  category: string | null;
  size?: number;
}) {
  return (
    <div
      className="grid shrink-0 place-items-center font-bold"
      style={{
        width: size,
        height: size,
        borderRadius: Math.round(size * 0.26),
        fontSize: Math.round(size * 0.4),
        color: categoryColor(category),
        background: categoryTint(category),
      }}
    >
      {initial}
    </div>
  );
}
