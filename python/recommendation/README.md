## Social Recommendation System

This example builds a social network graph and recommends content and friends to users.

### How It Works

1. Creates a graph of users, topics, and posts in IssunDB, with `FOLLOWS`, `POSTED`, `ABOUT`, and `LIKES` edges; each user has topic affinities
   that drive their interest vector.
2. Computes interest-vector embeddings for users and posts and builds a full-text index over post text, so the graph supports both semantic and
   keyword search.
3. Provides four recommendation features, including friend-of-friend suggestions through Cypher, kindred users and posts through vector search,
   trending topics through Cypher aggregation over recent likes, and a hybrid discover feed that fuses vector, text, and one-hop graph expansion.

More detailed workflow is shown below:

<div align="center">
  <picture>
    <img alt="Workflow" src="../../assets/diagrams/recommendation.svg" height="70%" width="70%">
  </picture>
</div>
