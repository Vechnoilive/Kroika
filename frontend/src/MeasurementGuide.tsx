export function MeasurementGuide({variant, label}: {variant: string; label: string}) {
  const isCircumference = /bust|waist|hip|neck|arc|arm|wrist|elbow|trousers/.test(variant);
  const isWidth = /width|span/.test(variant);
  const isAngle = /angle/.test(variant);
  const isShoulder = /shoulder/.test(variant);
  const level = variant.includes('waist') ? 112 : variant.includes('hip') ? 142 : 82;

  return (
    <figure className="measurement-guide">
      <svg viewBox="0 0 220 270" role="img" aria-labelledby="measurement-guide-title">
        <title id="measurement-guide-title">Схема: {label}</title>
        <circle className="guide-body" cx="110" cy="31" r="20" />
        <path className="guide-body" d="M81 61 Q110 49 139 61 L151 151 Q145 211 139 250 M81 61 L69 151 Q75 211 81 250 M90 60 Q83 105 86 157 L77 249 M130 60 Q137 105 134 157 L143 249" />
        <path className="guide-body" d="M82 68 L48 151 M138 68 L172 151" />
        {isCircumference && (
          <>
            <ellipse className="guide-measure" cx="110" cy={level} rx={level > 120 ? 38 : 33} ry="9" />
            <path className="guide-arrow" d={`M145 ${level - 1} l-7 -5 m7 5 l-7 5`} />
          </>
        )}
        {isWidth && (
          <>
            <line className="guide-measure" x1="78" y1="78" x2="142" y2="78" />
            <path className="guide-arrow" d="M78 78 l8 -5 m-8 5 l8 5 M142 78 l-8 -5 m8 5 l-8 5" />
          </>
        )}
        {!isCircumference && !isWidth && !isAngle && !isShoulder && (
          <>
            <line className="guide-measure" x1="155" y1="55" x2="155" y2="154" />
            <path className="guide-arrow" d="M155 55 l-5 8 m5 -8 l5 8 M155 154 l-5 -8 m5 8 l5 -8" />
          </>
        )}
        {isShoulder && !isAngle && (
          <>
            <line className="guide-measure" x1="107" y1="57" x2="140" y2="69" />
            <circle className="guide-point" cx="107" cy="57" r="4" />
            <circle className="guide-point" cx="140" cy="69" r="4" />
          </>
        )}
        {isAngle && (
          <>
            <line className="guide-reference" x1="104" y1="58" x2="147" y2="58" />
            <line className="guide-measure" x1="104" y1="58" x2="143" y2="72" />
            <path className="guide-measure" d="M128 58 A24 24 0 0 1 126 66" />
          </>
        )}
      </svg>
      <figcaption>Красная линия показывает направление ленты. Схема поясняющая, не масштабная.</figcaption>
    </figure>
  );
}
