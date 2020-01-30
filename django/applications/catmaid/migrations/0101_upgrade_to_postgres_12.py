from django.db import migrations

forward = """
  -- We want to be able to create these functions with a different return type.
  -- Therefore, we have have to delete them before they can be recreated.
  DROP FUNCTION IF EXISTS notify_conditionally;
  DROP FUNCTION IF EXISTS notify_conditionally_with_time;

  -- Enable spatial update events.
  CREATE OR REPLACE FUNCTION enable_spatial_update_events() RETURNS void
  LANGUAGE plpgsql AS
  $$
  BEGIN
    CREATE OR REPLACE FUNCTION notify_conditionally(channel text, payload text) RETURNS void
    LANGUAGE sql AS
    $inner$
        SELECT pg_notify(channel, payload);
    $inner$;

    -- This will create an event for a changed edge starting at treenode <arg1>
    -- with the location and parent node as of the current and last transaction,
    -- The transaction is represented by its txid and the tx start time.
    CREATE OR REPLACE FUNCTION
    notify_conditionally_tedgepair_with_txtime(channel text, arg1 anyelement) RETURNS void
    LANGUAGE sql AS
    $inner$
        SELECT pg_notify(channel, concat_ws(',', '["tedgepair"', arg1,
            txid_current(), extract(epoch from now()), ']'));
    $inner$;
  END;
  $$;

  -- Disable spatial update events. Using a simple SQL no-op allows the
  -- planner to replace the use of this function with a constant. By doing so it
  -- also doesn't need to evaluate the parameter string concatenation anymore.
  CREATE OR REPLACE FUNCTION disable_spatial_update_events() RETURNS void
  LANGUAGE plpgsql AS
  $$
  BEGIN
     CREATE OR REPLACE FUNCTION notify_conditionally(channel text, payload text) RETURNS void
     LANGUAGE sql AS
     $inner$
     $inner$;

     CREATE OR REPLACE FUNCTION notify_conditionally_with_time(channel text, arg1 anyelement) RETURNS void
     LANGUAGE sql AS
     $inner$
     $inner$;

     CREATE OR REPLACE FUNCTION
     notify_conditionally_tedgepair_with_txtime(channel text, arg1 anyelement) RETURNS void
     LANGUAGE sql AS
     $inner$
     $inner$;
  END;
  $$;

  -- Make sure these functions are registeredd in some form.
  SELECT disable_spatial_update_events();

  -- Note that this trigger function relies in manu places on transition
  -- tables. Unfortunately, these come without statistics and we use a LIMIT
  -- clause to hint to the planner how many entries are in a transition table.
  -- And we find out how many entries are in there by counting them. This
  -- works surprisingly well.
  CREATE OR REPLACE FUNCTION on_edit_treenode_update_summary_and_edges() RETURNS trigger
  LANGUAGE plpgsql AS
  $$
  BEGIN
      WITH old_new AS MATERIALIZED (
          SELECT t.*,
            ot.location_x AS old_location_x,
            ot.location_y AS old_location_y,
            ot.location_z AS old_location_z,
            ot.edition_time as old_edition_time,
            ot.creation_time AS old_creation_time,
            ot.skeleton_id AS old_skeleton_id
          FROM old_treenode ot
          JOIN new_treenode t
                ON t.id = ot.id
          WHERE ot.parent_id IS DISTINCT FROM t.parent_id
            OR ot.location_x != t.location_x
            OR ot.location_y != t.location_y
            OR ot.location_z != t.location_z
            OR ot.skeleton_id != t.skeleton_id
      ), updated_edge_data AS MATERIALIZED (
          (
              -- Find all nodes that changed their position or parent
              SELECT ton.id, ton.project_id, ton.skeleton_id, ton.creation_time,
                  ton.edition_time, ton.editor_id, ST_MakeLine(
                      ST_MakePoint(ton.location_x, ton.location_y, ton.location_z),
                      ST_MakePoint(p.location_x, p.location_y, p.location_z)
                  ) AS edge,
                  ton.parent_id,
                  ton.old_edition_time,
                  ton.old_creation_time,
                  ton.old_skeleton_id,
                  notify_conditionally('catmaid.spatial-update', concat_ws(',',
                      '[', ton.project_id, 'edges', '2',
                      ton.location_x, ton.location_y, ton.location_z,
                      p.location_x, p.location_y, p.location_z,
                      ton.old_location_x, ton.old_location_y, ton.old_location_z,
                      p.location_x, p.location_y, p.location_z, ']'))
              FROM old_new ton
              JOIN LATERAL (
                SELECT * from treenode p
                WHERE (ton.parent_id IS NOT NULL AND p.id = ton.parent_id)
              ) p
                ON TRUE

              UNION ALL

              -- Find all nodes that changed their position or parent
              SELECT ton.id, ton.project_id, ton.skeleton_id, ton.creation_time,
                  ton.edition_time, ton.editor_id, ST_MakeLine(
                      ST_MakePoint(ton.location_x, ton.location_y, ton.location_z),
                      ST_MakePoint(p.location_x, p.location_y, p.location_z)
                  ) AS edge,
                  ton.parent_id,
                  ton.old_edition_time,
                  ton.old_creation_time,
                  ton.old_skeleton_id,
                  notify_conditionally('catmaid.spatial-update', concat_ws(',',
                      '[', ton.project_id, 'edges', '2',
                      ton.location_x, ton.location_y, ton.location_z,
                      p.location_x, p.location_y, p.location_z,
                      ton.old_location_x, ton.old_location_y, ton.old_location_z,
                      p.location_x, p.location_y, p.location_z, ']'))
              FROM old_new ton
              JOIN LATERAL (
                SELECT * from treenode p
                WHERE (ton.parent_id IS NULL AND p.id = ton.id)
              ) p
                ON TRUE
          )
          UNION ALL
          (
              SELECT c.id, c.project_id, c.skeleton_id, c.creation_time,
                  c.edition_time, c.editor_id, ST_MakeLine(
                      ST_MakePoint(c.location_x, c.location_y, c.location_z),
                      ST_MakePoint(e.location_x, e.location_y, e.location_z)
                  ) AS edge,
                  c.parent_id,
                  c.edition_time AS old_edition_time,
                  c.creation_time AS old_creation_time,
                  c.skeleton_id AS old_skeleton_id,
                  notify_conditionally('catmaid.spatial-update', concat_ws(',',
                      '[', e.project_id, 'edges', '2',
                      c.location_x, c.location_y, c.location_z,
                      e.location_x, e.location_y, e.location_z,
                      c.location_x, c.location_y, c.location_z,
                      ot.location_x, ot.location_y, ot.location_z, ']'))
              FROM treenode c
              JOIN (
                  SELECT * FROM old_treenode
                  LIMIT (SELECT COUNT(*) FROM old_treenode)
              ) ot
                  ON ot.id = c.parent_id
              JOIN (
                  SELECT * FROM new_treenode
                  LIMIT (SELECT COUNT(*) FROM new_treenode)
              ) e
                  ON c.parent_id = e.id
              -- Use anti-join to only look at those edges that are not also
              -- already included as parent edge in the first part of the UNION.LL
              LEFT JOIN (
                  SELECT * FROM new_treenode
                  LIMIT (SELECT COUNT(*) FROM new_treenode)
              ) c2
                  ON c.id = c2.id
              WHERE c2.id IS NULL
          )
      ), old_edge AS MATERIALIZED (
          -- Get all old edges of changed nodes as well as their
          -- children (if any). Child edges contribute to the cable
          -- length as well and need to be updated.
          -- This is also an alternative place where the pg_notify call could be
          -- made:
          -- notify_conditionally_tedgepair_with_txtime('catmaid.spatial-update', t.id)
          SELECT t.id, t.project_id, t.old_skeleton_id AS skeleton_id,
              t.old_creation_time AS creation_time,
              t.old_edition_time AS edition_time,
              e.edge,
              t.editor_id
          FROM updated_edge_data t
          JOIN treenode_edge e
              ON e.id = t.id
      ), updated_edge AS MATERIALIZED (
          -- Update all changed edges. To have this join work fast, we
          -- rely on reasonable statistics on the row count of
          -- updated_edge_data. This is provided, by setting (obivious)
          -- limits on its size when creating it.
          UPDATE treenode_edge e
          SET edge = ue.edge, parent_id = ue.parent_id
          FROM updated_edge_data ue
          WHERE e.id = ue.id
          RETURNING e.id
      ), new_edge AS NOT MATERIALIZED (
          -- Collect changed nodes both with and without location
          -- change. Updated edge information takes precedence.
          SELECT ue.id, ue.project_id, ue.skeleton_id,
              ue.creation_time, ue.edition_time, ue.edge, ue.editor_id
          FROM updated_edge_data ue
          UNION ALL
          SELECT nt.id, nt.project_id, nt.skeleton_id,
              nt.creation_time, nt.edition_time, oe.edge, nt.editor_id
          FROM (
              SELECT * FROM new_treenode
              LIMIT (SELECT COUNT(*) FROM new_treenode)
          ) nt
          LEFT JOIN updated_edge_data ue
              ON nt.id = ue.id
          JOIN old_edge oe
              ON nt.id = oe.id
          WHERE ue.id IS NULL
      ), old_skeleton_data AS MATERIALIZED (
          -- Aggregate data over old skeleton datas to delete for summary.
          SELECT skeleton_id, project_id,
              -COUNT(*) AS num_nodes,
              -SUM(ST_3DLength(edge)) AS length,
              MIN(creation_time) AS min_creation_time,
              MAX(edition_time) AS max_edition_time,
              last_editor_id
          FROM (
              SELECT skeleton_id, project_id, edge, creation_time, edition_time,
                  first_value(editor_id) OVER w AS last_editor_id
              FROM old_edge
              WINDOW w AS (PARTITION BY skeleton_id, project_id ORDER BY edition_time DESC)
          ) edge_info
          GROUP BY skeleton_id, project_id, last_editor_id
      ), new_skeleton_data AS NOT MATERIALIZED (
          -- Aggregate data over skeletons to prepare for summary update.
          SELECT skeleton_id, project_id,
              COUNT(*) AS num_nodes,
              SUM(ST_3DLength(edge)) AS length,
              MIN(creation_time) AS min_creation_time,
              MAX(edition_time) AS max_edition_time,
              last_editor_id
          FROM (
              SELECT skeleton_id, project_id, edge, creation_time, edition_time,
                  first_value(editor_id) OVER w AS last_editor_id
              FROM new_edge
              WINDOW w AS (PARTITION BY skeleton_id, project_id ORDER BY edition_time DESC)
          ) edge_info
          GROUP BY skeleton_id, project_id, last_editor_id
      ), old_skeletons_with_imported_nodes AS NOT MATERIALIZED (
          SELECT osd.skeleton_id, num_imported_nodes
          FROM old_skeleton_data osd
          JOIN catmaid_skeleton_summary css
              ON css.skeleton_id = osd.skeleton_id
          WHERE num_imported_nodes > 0
      ), imported_nodes AS MATERIALIZED (
          -- Count nodes that were originally imported from another
          -- project/instance, per old skeleton version.
          SELECT t.id, t.skeleton_id AS old_skeleton_id
          FROM old_treenode t
          JOIN old_skeletons_with_imported_nodes oswin
              ON oswin.skeleton_id = t.skeleton_id
          JOIN LATERAL (
              -- Get original transaction ID and creation time
              SELECT txid, edition_time
              FROM treenode__with_history th
              WHERE th.id = t.id
              ORDER BY edition_time ASC
              LIMIT 1
          ) t_origin
              ON TRUE
          JOIN catmaid_transaction_info cti
              ON cti.transaction_id = t_origin.txid
                  -- A transaction ID is only unique with a date.
                  AND cti.execution_time = t_origin.edition_time
          WHERE cti.label = 'skeletons.import'
      ), old_imported_nodes AS NOT MATERIALIZED (
          -- Count nodes that were originally imported from another
          -- project/instance, per old skeleton version.
          SELECT ins.old_skeleton_id AS skeleton_id, COUNT(*) AS num_imported_nodes
          FROM imported_nodes ins
          GROUP BY ins.old_skeleton_id
      ), new_imported_nodes AS NOT MATERIALIZED (
          -- Count nodes that were originally imported from another
          -- project/instance, per old skeleton version. It is okay to
          -- use the old skeleton here, because the fact whether a node
          -- was imported, will not change between new/old.
          SELECT nt.skeleton_id, COUNT(*) AS num_imported_nodes
          FROM imported_nodes ins
          JOIN new_treenode nt
              ON nt.id = ins.id
          GROUP BY nt.skeleton_id
      ), summary_update_delta AS NOT MATERIALIZED (
          SELECT skeleton_id, project_id,
              SUM(num_nodes) AS num_nodes,
              SUM(length) AS length,
              MIN(min_creation_time) AS min_creation_time,
              MAX(max_edition_time) AS max_edition_time,
              last_editor_id,
              SUM(num_imported_nodes) AS num_imported_nodes
          FROM (
              SELECT skeleton_id, project_id, num_nodes, length,
                  min_creation_time, max_edition_time,
                  first_value(last_editor_id) OVER w AS last_editor_id,
                  COALESCE(num_imported_nodes, 0) AS num_imported_nodes
              FROM (
                  (
                      SELECT os.skeleton_id, os.project_id, os.num_nodes,
                          os.length, os.min_creation_time, os.max_edition_time,
                          os.last_editor_id, -1 * ins.num_imported_nodes AS num_imported_nodes
                      FROM old_skeleton_data os
                      LEFT JOIN old_imported_nodes ins
                          ON ins.skeleton_id = os.skeleton_id
                  )
                  UNION ALL
                  (
                      SELECT ns.skeleton_id, ns.project_id, ns.num_nodes,
                          ns.length, ns.min_creation_time, ns.max_edition_time,
                          ns.last_editor_id, ins.num_imported_nodes
                      FROM new_skeleton_data ns
                      LEFT JOIN new_imported_nodes ins
                          ON ins.skeleton_id = ns.skeleton_id
                  )
              ) _update_data
              WINDOW w AS (PARTITION BY skeleton_id, project_id ORDER BY max_edition_time DESC)
          ) update_data
          GROUP BY skeleton_id, project_id, last_editor_id
      )
      INSERT INTO catmaid_skeleton_summary (project_id, skeleton_id,
          last_summary_update, original_creation_time,
          last_edition_time, last_editor_id, num_nodes, cable_length,
          num_imported_nodes)
      (
          SELECT s.project_id, s.skeleton_id, now(), s.min_creation_time,
              s.max_edition_time,
              COALESCE(NULLIF(current_setting('catmaid.user_id', TRUE), '')::integer, s.last_editor_id),
              s.num_nodes, s.length, s.num_imported_nodes
          FROM summary_update_delta s
      )
      ON CONFLICT (skeleton_id) DO UPDATE
      SET num_nodes = catmaid_skeleton_summary.num_nodes + EXCLUDED.num_nodes,
          last_summary_update = EXCLUDED.last_summary_update,
          last_edition_time = GREATEST(
              catmaid_skeleton_summary.last_edition_time,
              EXCLUDED.last_edition_time),
          last_editor_id = EXCLUDED.last_editor_id,
          cable_length = catmaid_skeleton_summary.cable_length + EXCLUDED.cable_length,
          num_imported_nodes = catmaid_skeleton_summary.num_imported_nodes + EXCLUDED.num_imported_nodes;

      RETURN NEW;
  END;
  $$;
"""

backward = """
  -- We want to be able to create these functions with a different return type.
  -- Therefore, we have have to delete them before they can be recreated.
  DROP FUNCTION IF EXISTS notify_conditionally;
  DROP FUNCTION IF EXISTS notify_conditionally_with_time;
  DROP FUNCTION IF EXISTS Pnotify_conditionally_tedgepair_with_txtime;

  CREATE OR REPLACE FUNCTION enable_spatial_update_events() RETURNS void
  LANGUAGE plpgsql AS
  $$
  BEGIN
      CREATE OR REPLACE FUNCTION notify_conditionally(channel text, payload text) RETURNS int
      LANGUAGE plpgsql STABLE AS
      $inner$
      BEGIN
          PERFORM pg_notify(channel, payload);
          RETURN 0;
      END;
      $inner$;

      CREATE OR REPLACE FUNCTION notify_conditionally_with_time(channel text, arg1 anyelement) RETURNS int
      LANGUAGE plpgsql STABLE AS
      $inner$
      BEGIN
          PERFORM pg_notify(channel, arg1 || ',' || extract(epoch from now()));
          RETURN 0;
      END;
      $inner$;
  END;
  $$;

  -- Disable spatial update events. The resulting functions can be marked as
  -- IMMUTABLE, because the function will always return the same value (for
  -- any input), which can be optimized by the planner.
  CREATE OR REPLACE FUNCTION disable_spatial_update_events() RETURNS void
  LANGUAGE plpgsql AS
  $$
  BEGIN
      CREATE OR REPLACE FUNCTION notify_conditionally(channel text, payload text) RETURNS int
      LANGUAGE plpgsql IMMUTABLE AS
      $inner$
      BEGIN
          PERFORM 1 WHERE 1 = 0;
          RETURN 0;
      END;
      $inner$;

      CREATE OR REPLACE FUNCTION notify_conditionally_with_time(channel text, arg1 anyelement) RETURNS int
      LANGUAGE plpgsql IMMUTABLE AS
      $inner$
      BEGIN
          PERFORM 1 WHERE 1 = 0;
          RETURN 0;
      END;
      $inner$;
  END;
  $$;

  -- Make sure functions are registere in some form.
  SELECT disable_spatial_update_events();

  -- Note that this trigger function relies in manu places on transition
  -- tables. Unfortunately, these come without statistics and we use a LIMIT
  -- clause to hint to the planner how many entries are in a transition table.
  -- And we find out how many entries are in there by counting them. This
  -- works surprisingly well.
  CREATE OR REPLACE FUNCTION on_edit_treenode_update_summary_and_edges() RETURNS trigger
  LANGUAGE plpgsql AS
  $$
  BEGIN
      WITH updated_edge_data AS MATERIALIZED (
          (
              -- Find all nodes that changed their position or parent
              SELECT t.id, t.project_id, t.skeleton_id, t.creation_time,
                  t.edition_time, t.editor_id, ST_MakeLine(
                      ST_MakePoint(t.location_x, t.location_y, t.location_z),
                      ST_MakePoint(p.location_x, p.location_y, p.location_z)
                  ) AS edge,
                  t.parent_id,
                  ot.edition_time as old_edition_time,
                  ot.creation_time AS old_creation_time,
                  ot.skeleton_id AS old_skeleton_id,
                  -- Trigger event with information on changed edges (old and new)
                  -- as JSON encoded payload.
                  --notify_conditionally('catmaid.spatial-update', 'a')
                  notify_conditionally('catmaid.spatial-update', concat_ws(',',
                      '[', t.project_id, 'edges', '2',
                      t.location_x, t.location_y, t.location_z,
                      p.location_x, p.location_y, p.location_z,
                      ot.location_x, ot.location_y, ot.location_z,
                      p.location_x, p.location_y, p.location_z, ']'))
              FROM treenode p
              JOIN (
                      SELECT * FROM new_treenode
                      LIMIT (SELECT COUNT(*) FROM new_treenode)
                  ) t
                  ON (t.parent_id IS NOT NULL AND p.id = t.parent_id) OR
                      (t.parent_id IS NULL AND p.id = t.id)
              JOIN (
                      SELECT * FROM old_treenode
                      LIMIT (SELECT COUNT(*) FROM old_treenode)
                  ) ot
                  ON ot.id = t.id
              WHERE ot.parent_id IS DISTINCT FROM t.parent_id OR
                 ot.location_x != t.location_x OR
                 ot.location_y != t.location_y OR
                 ot.location_z != t.location_z OR
                 ot.skeleton_id != t.skeleton_id
          )
          UNION ALL
          (
              SELECT c.id, c.project_id, c.skeleton_id, c.creation_time,
                  c.edition_time, c.editor_id, ST_MakeLine(
                      ST_MakePoint(c.location_x, c.location_y, c.location_z),
                      ST_MakePoint(e.location_x, e.location_y, e.location_z)
                  ) AS edge,
                  c.parent_id,
                  c.edition_time AS old_edition_time,
                  c.creation_time AS old_creation_time,
                  c.skeleton_id AS old_skeleton_id,
                  -- Trigger event with edge information as JSON encoded payload.
                  --notify_conditionally('catmaid.spatial-update', 'b')
                  notify_conditionally('catmaid.spatial-update', concat_ws(',',
                      '[', e.project_id, 'edges', '2',
                      c.location_x, c.location_y, c.location_z,
                      e.location_x, e.location_y, e.location_z,
                      c.location_x, c.location_y, c.location_z,
                      ot.location_x, ot.location_y, ot.location_z, ']'))
              FROM treenode c
              JOIN (
                  SELECT * FROM old_treenode
                  LIMIT (SELECT COUNT(*) FROM old_treenode)
              ) ot
                  ON ot.id = c.parent_id
              JOIN (
                  SELECT * FROM new_treenode
                  LIMIT (SELECT COUNT(*) FROM new_treenode)
              ) e
                  ON c.parent_id = e.id
              LEFT JOIN (
                  SELECT * FROM new_treenode
                  LIMIT (SELECT COUNT(*) FROM new_treenode)
              ) c2
                  ON c.id = c2.id
              WHERE c2.id IS NULL
          )
      ), old_edge AS MATERIALIZED (
          -- Get all old edges of changed nodes as well as their
          -- children (if any). Child edges contribute to the cable
          -- length as well and need to be updated.
          SELECT t.id, t.project_id, t.old_skeleton_id AS skeleton_id,
              t.old_creation_time AS creation_time,
              t.old_edition_time AS edition_time,
              e.edge,
              t.editor_id
          FROM updated_edge_data t
          JOIN treenode_edge e
              ON e.id = t.id
      ), updated_edge AS MATERIALIZED (
          -- Update all changed edges. To have this join work fast, we
          -- rely on reasonable statistics on the row count of
          -- updated_edge_data. This is provided, by setting (obivious)
          -- limits on its size when creating it.
          UPDATE treenode_edge e
          SET edge = ue.edge, parent_id = ue.parent_id
          FROM updated_edge_data ue
          WHERE e.id = ue.id
          RETURNING e.id
      ), new_edge AS NOT MATERIALIZED (
          -- Collect changed nodes both with and without location
          -- change. Updated edge information takes precedence.
          SELECT ue.id, ue.project_id, ue.skeleton_id,
              ue.creation_time, ue.edition_time, ue.edge, ue.editor_id
          FROM updated_edge_data ue
          UNION ALL
          SELECT nt.id, nt.project_id, nt.skeleton_id,
              nt.creation_time, nt.edition_time, oe.edge, nt.editor_id
          FROM (
              SELECT * FROM new_treenode
              LIMIT (SELECT COUNT(*) FROM new_treenode)
          ) nt
          LEFT JOIN updated_edge_data ue
              ON nt.id = ue.id
          JOIN old_edge oe
              ON nt.id = oe.id
          WHERE ue.id IS NULL
      ), old_skeleton_data AS MATERIALIZED (
          -- Aggregate data over old skeleton datas to delete for summary.
          SELECT skeleton_id, project_id,
              -COUNT(*) AS num_nodes,
              -SUM(ST_3DLength(edge)) AS length,
              MIN(creation_time) AS min_creation_time,
              MAX(edition_time) AS max_edition_time,
              last_editor_id
          FROM (
              SELECT skeleton_id, project_id, edge, creation_time, edition_time,
                  first_value(editor_id) OVER w AS last_editor_id
              FROM old_edge
              WINDOW w AS (PARTITION BY skeleton_id, project_id ORDER BY edition_time DESC)
          ) edge_info
          GROUP BY skeleton_id, project_id, last_editor_id
      ), new_skeleton_data AS NOT MATERIALIZED (
          -- Aggregate data over skeletons to prepare for summary update.
          SELECT skeleton_id, project_id,
              COUNT(*) AS num_nodes,
              SUM(ST_3DLength(edge)) AS length,
              MIN(creation_time) AS min_creation_time,
              MAX(edition_time) AS max_edition_time,
              last_editor_id
          FROM (
              SELECT skeleton_id, project_id, edge, creation_time, edition_time,
                  first_value(editor_id) OVER w AS last_editor_id
              FROM new_edge
              WINDOW w AS (PARTITION BY skeleton_id, project_id ORDER BY edition_time DESC)
          ) edge_info
          GROUP BY skeleton_id, project_id, last_editor_id
      ), old_skeletons_with_imported_nodes AS NOT MATERIALIZED (
          SELECT osd.skeleton_id, num_imported_nodes
          FROM old_skeleton_data osd
          JOIN catmaid_skeleton_summary css
              ON css.skeleton_id = osd.skeleton_id
          WHERE num_imported_nodes > 0
      ), imported_nodes AS MATERIALIZED (
          -- Count nodes that were originally imported from another
          -- project/instance, per old skeleton version.
          SELECT t.id, t.skeleton_id AS old_skeleton_id
          FROM old_treenode t
          JOIN old_skeletons_with_imported_nodes oswin
              ON oswin.skeleton_id = t.skeleton_id
          JOIN LATERAL (
              -- Get original transaction ID and creation time
              SELECT txid, edition_time
              FROM treenode__with_history th
              WHERE th.id = t.id
              ORDER BY edition_time ASC
              LIMIT 1
          ) t_origin
              ON TRUE
          JOIN catmaid_transaction_info cti
              ON cti.transaction_id = t_origin.txid
                  -- A transaction ID is only unique with a date.
                  AND cti.execution_time = t_origin.edition_time
          WHERE cti.label = 'skeletons.import'
      ), old_imported_nodes AS NOT MATERIALIZED (
          -- Count nodes that were originally imported from another
          -- project/instance, per old skeleton version.
          SELECT ins.old_skeleton_id AS skeleton_id, COUNT(*) AS num_imported_nodes
          FROM imported_nodes ins
          GROUP BY ins.old_skeleton_id
      ), new_imported_nodes AS NOT MATERIALIZED (
          -- Count nodes that were originally imported from another
          -- project/instance, per old skeleton version. It is okay to
          -- use the old skeleton here, because the fact whether a node
          -- was imported, will not change between new/old.
          SELECT nt.skeleton_id, COUNT(*) AS num_imported_nodes
          FROM imported_nodes ins
          JOIN new_treenode nt
              ON nt.id = ins.id
          GROUP BY nt.skeleton_id
      ), summary_update_delta AS NOT MATERIALIZED (
          SELECT skeleton_id, project_id,
              SUM(num_nodes) AS num_nodes,
              SUM(length) AS length,
              MIN(min_creation_time) AS min_creation_time,
              MAX(max_edition_time) AS max_edition_time,
              last_editor_id,
              SUM(num_imported_nodes) AS num_imported_nodes
          FROM (
              SELECT skeleton_id, project_id, num_nodes, length,
                  min_creation_time, max_edition_time,
                  first_value(last_editor_id) OVER w AS last_editor_id,
                  COALESCE(num_imported_nodes, 0) AS num_imported_nodes
              FROM (
                  (
                      SELECT os.skeleton_id, os.project_id, os.num_nodes,
                          os.length, os.min_creation_time, os.max_edition_time,
                          os.last_editor_id, -1 * ins.num_imported_nodes AS num_imported_nodes
                      FROM old_skeleton_data os
                      LEFT JOIN old_imported_nodes ins
                          ON ins.skeleton_id = os.skeleton_id
                  )
                  UNION ALL
                  (
                      SELECT ns.skeleton_id, ns.project_id, ns.num_nodes,
                          ns.length, ns.min_creation_time, ns.max_edition_time,
                          ns.last_editor_id, ins.num_imported_nodes
                      FROM new_skeleton_data ns
                      LEFT JOIN new_imported_nodes ins
                          ON ins.skeleton_id = ns.skeleton_id
                  )
              ) _update_data
              WINDOW w AS (PARTITION BY skeleton_id, project_id ORDER BY max_edition_time DESC)
          ) update_data
          GROUP BY skeleton_id, project_id, last_editor_id
      )
      INSERT INTO catmaid_skeleton_summary (project_id, skeleton_id,
          last_summary_update, original_creation_time,
          last_edition_time, last_editor_id, num_nodes, cable_length,
          num_imported_nodes)
      (
          SELECT s.project_id, s.skeleton_id, now(), s.min_creation_time,
              s.max_edition_time,
              COALESCE(NULLIF(current_setting('catmaid.user_id', TRUE), '')::integer, s.last_editor_id),
              s.num_nodes, s.length, s.num_imported_nodes
          FROM summary_update_delta s
      )
      ON CONFLICT (skeleton_id) DO UPDATE
      SET num_nodes = catmaid_skeleton_summary.num_nodes + EXCLUDED.num_nodes,
          last_summary_update = EXCLUDED.last_summary_update,
          last_edition_time = GREATEST(
              catmaid_skeleton_summary.last_edition_time,
              EXCLUDED.last_edition_time),
          last_editor_id = EXCLUDED.last_editor_id,
          cable_length = catmaid_skeleton_summary.cable_length + EXCLUDED.cable_length,
          num_imported_nodes = catmaid_skeleton_summary.num_imported_nodes + EXCLUDED.num_imported_nodes;

      RETURN NEW;
  END;
  $$;
"""

class Migration(migrations.Migration):

    dependencies = [
        ('catmaid', '0100_update_timestamp_field_default_values'),
    ]

    operations = [
        migrations.RunSQL(forward, backward),
    ]
