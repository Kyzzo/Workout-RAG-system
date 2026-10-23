import ProgramWorkspace from "./ProgramWorkspace";

// Open to signed-out visitors: they see the generator and the evidence
// assistant as a guest, and any interaction opens sign-in (ProgramWorkspace).
export default function Home() {
  return (
    <div className="flex flex-1 flex-col">
      <ProgramWorkspace />
    </div>
  );
}
