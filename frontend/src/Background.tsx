import { useEffect, useRef, useState } from "react";
import type { Speed } from "./api";

export const durations: Record<Speed, number> = {
  fast: 150,
  normal: 300,
  slow: 600,
};
const fallback = "/assets/frostwake.png";

export function Background({ url, speed }: { url: string; speed: Speed }) {
  const [layers, setLayers] = useState([{ source: fallback, id: 0 }]);
  const request = useRef(0);
  useEffect(() => {
    const generation = ++request.current;
    let cleanup: ReturnType<typeof setTimeout>;
    const show = (source: string) => {
      if (generation !== request.current) return;
      setLayers((previous) =>
        previous.at(-1)?.source === source
          ? previous
          : [...previous, { source, id: generation }],
      );
      cleanup = setTimeout(() => {
        if (generation === request.current)
          setLayers([{ source, id: generation }]);
      }, durations[speed] + 80);
    };
    const pending: HTMLImageElement[] = [];
    const load = (source: string) => {
      const image = new Image();
      pending.push(image);
      image.onload = () => show(source);
      image.onerror = () => {
        if (generation === request.current && source !== fallback)
          load(fallback);
        // Retain the last good layer if even the default artwork cannot load.
      };
      image.src = source;
    };
    load(url);
    return () => {
      request.current++;
      clearTimeout(cleanup);
      pending.forEach((image) => {
        image.onload = null;
        image.onerror = null;
      });
    };
  }, [url, speed]);
  return (
    <div
      className="backdrop"
      aria-hidden="true"
      style={
        {
          "--background-duration": `${durations[speed]}ms`,
        } as React.CSSProperties
      }
    >
      {layers.map(({ source, id }, index) => (
        <div
          key={id}
          className={`backdrop-image ${index ? "entering" : ""}`}
          style={{ backgroundImage: `url("${source}")` }}
        />
      ))}
      <div className="backdrop-shade" />
    </div>
  );
}
