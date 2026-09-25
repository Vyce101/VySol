import { useEffect, useState } from "react";
import { BookOpen, HouseLine } from "@phosphor-icons/react";

export function WorldSectionsNav({
  section,
  onOverview,
  onChronicles,
  attentionEpoch = 0,
}: {
  section: "overview" | "chronicles";
  onOverview: () => void;
  onChronicles: () => void;
  attentionEpoch?: number;
}) {
  const [showAttention, setShowAttention] = useState(false);

  useEffect(() => {
    if (!attentionEpoch) return;
    setShowAttention(true);
    const timer = window.setTimeout(() => setShowAttention(false), 1800);
    return () => window.clearTimeout(timer);
  }, [attentionEpoch]);

  return (
    <aside className="world-overview-sidebar">
      <nav aria-label="World sections">
        <button
          type="button"
          aria-current={section === "overview" ? "page" : undefined}
          className={showAttention ? "world-overview-attention" : undefined}
          onClick={onOverview}
        >
          <HouseLine size={19} aria-hidden="true" /> Overview
        </button>
        <button
          type="button"
          aria-current={section === "chronicles" ? "page" : undefined}
          onClick={onChronicles}
        >
          <BookOpen size={19} aria-hidden="true" /> Chronicles
        </button>
      </nav>
    </aside>
  );
}
