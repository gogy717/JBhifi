import { ReservedPage } from "@/components/shop/reserved";

export default async function CataloguePage({ searchParams }: PageProps<"/products">) {
  const { q, category } = await searchParams;
  const query = typeof q === "string" ? q.trim() : "";
  const categoryId = typeof category === "string" ? category : "";
  return (
    <ReservedPage id="catalogue">
      {(query || categoryId) && (
        <>
          Already wired: this page received{query && <> the search <b>“{query}”</b></>}
          {query && categoryId && " and"}{categoryId && <> category <b>{categoryId}</b></>} from the header.
        </>
      )}
    </ReservedPage>
  );
}
