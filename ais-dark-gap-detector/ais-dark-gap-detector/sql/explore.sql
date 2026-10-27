-- Run inside the DuckDB service:
--   docker compose run --rm duckdb -init sql/explore.sql
-- Paths are relative to /work, which is the project root (data/ and outputs/ are mounted).
.mode duckbox

-- Cleaned pings written by the pipeline (after you've run it once on real data)
CREATE OR REPLACE VIEW pings AS SELECT * FROM read_parquet('outputs/clean_pings.parquet');
CREATE OR REPLACE VIEW gaps  AS SELECT * FROM read_csv('outputs/gaps_scored.csv');

.print 'Views ready: pings, gaps.  Try:'
.print '  SELECT count(*), count(DISTINCT mmsi) FROM pings;'
.print '  SELECT mmsi, vessel_group, round(duration_h,1) h, round(dist_coast_km) coast_km, round(rule_score,2) rule_s FROM gaps WHERE NOT near_edge AND NOT in_port_powerdown ORDER BY ensemble_rank_score LIMIT 20;'
.print '  SELECT mmsi, count(*) n_gaps, round(sum(duration_h),1) dark_hours FROM gaps GROUP BY mmsi HAVING n_gaps > 1 ORDER BY n_gaps DESC LIMIT 20;'
