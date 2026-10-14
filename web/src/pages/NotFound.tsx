import { Compass } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/Feedback";

export function NotFound() {
  return <Card><EmptyState as="h1" icon={<Compass className="size-6" />} title="Halaman tidak ditemukan" action={<Link to="/"><Button variant="primary">Ke daftar rapat</Button></Link>}>Alamat ini tidak ada di Rekamind.</EmptyState></Card>;
}
