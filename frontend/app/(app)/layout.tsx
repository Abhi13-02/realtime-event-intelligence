import { auth } from "@/auth";
import Shell from "@/components/shell";
import { WebSocketProvider } from "@/lib/websocket";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  const userName = session?.user?.name ?? "Analyst";

  return (
    <WebSocketProvider>
      <Shell userName={userName}>{children}</Shell>
    </WebSocketProvider>
  );
}
