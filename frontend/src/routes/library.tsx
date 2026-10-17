import { createFileRoute } from '@tanstack/react-router'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { SearchPanel, AskPanel, DistillPanel, ReviewPanel } from '@/components/library'

export const Route = createFileRoute('/library')({
  component: LibraryRoute,
})

function LibraryRoute() {
  return (
    <div className="bg-card rounded-xl shadow-lg p-4 sm:p-6 md:p-8">
      <header className="mb-4 sm:mb-6">
        <h1 className="text-lg sm:text-xl font-bold tracking-tight">Library</h1>
        <p className="text-xs sm:text-sm text-muted-foreground mt-1">
          Search, question, and synthesize across everything you've ingested.
        </p>
      </header>

      <Tabs defaultValue="search">
        <TabsList className="mb-4">
          <TabsTrigger value="search">Search</TabsTrigger>
          <TabsTrigger value="ask">Ask</TabsTrigger>
          <TabsTrigger value="distill">Distill</TabsTrigger>
          <TabsTrigger value="review">Review calls</TabsTrigger>
        </TabsList>

        <TabsContent value="search">
          <SearchPanel />
        </TabsContent>
        <TabsContent value="ask">
          <AskPanel />
        </TabsContent>
        <TabsContent value="distill">
          <DistillPanel />
        </TabsContent>
        <TabsContent value="review">
          <ReviewPanel />
        </TabsContent>
      </Tabs>
    </div>
  )
}
