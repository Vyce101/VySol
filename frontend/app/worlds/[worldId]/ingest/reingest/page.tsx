"use client";

import { use } from "react";
import WorldReingestSetupContent from "@/components/WorldReingestSetupContent";

export default function ReingestSetupPage({ params }: { params: Promise<{ worldId: string }> }) {
    const { worldId } = use(params);
    return <WorldReingestSetupContent worldId={worldId} mode="page" />;
}
