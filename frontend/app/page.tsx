import { auth } from "@clerk/nextjs/server";
import ProgramWorkspace from "./ProgramWorkspace";

export default async function Home() {
  await auth.protect();

  return (
    <div className="flex flex-1 flex-col">
      <ProgramWorkspace />
    </div>
  );
}
