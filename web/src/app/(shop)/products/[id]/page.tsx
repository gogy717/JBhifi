import { ReservedPage } from "@/components/shop/reserved";

export default async function ProductPage({ params }: PageProps<"/products/[id]">) {
  const { id } = await params;
  return <ReservedPage id="product">Already wired: links from the home page arrive here with product <b>{id}</b>.</ReservedPage>;
}
