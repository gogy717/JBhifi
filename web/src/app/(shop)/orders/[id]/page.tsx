import { ReservedPage } from "@/components/shop/reserved";

export default async function OrderPage({ params }: PageProps<"/orders/[id]">) {
  const { id } = await params;
  return <ReservedPage id="order">Order <b>{id}</b>.</ReservedPage>;
}
