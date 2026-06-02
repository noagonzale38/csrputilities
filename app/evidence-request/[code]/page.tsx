import EvidenceRequestViewer from "./EvidenceRequestViewer";

type EvidenceRequestPageProps = {
  params: Promise<{ code: string }>;
};

export default async function EvidenceRequestPage({ params }: EvidenceRequestPageProps) {
  const { code } = await params;
  return <EvidenceRequestViewer code={code} />;
}
