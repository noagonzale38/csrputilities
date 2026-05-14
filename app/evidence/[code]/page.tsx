import EvidenceViewer from "./EvidenceViewer";

type EvidencePageProps = {
  params: Promise<{ code: string }>;
};

export default async function EvidencePage({ params }: EvidencePageProps) {
  const { code } = await params;
  return <EvidenceViewer code={code} />;
}
