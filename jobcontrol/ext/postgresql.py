"""
PostgreSQL-backed Job control class.
"""

from datetime import datetime, timedelta
from urlparse import urlparse, parse_qs

import psycopg2
import psycopg2.extras

from jobcontrol.interfaces import StorageBase
from jobcontrol.exceptions import NotFound


class PostgreSQLStorage(StorageBase):
    def __init__(self, dbconf, table_prefix='jobcontrol_'):
        self._dbconf = dbconf
        if table_prefix is None:
            table_prefix = ''
        self._table_prefix = table_prefix
        # self._local = Local()
        self._db = None

    @classmethod
    def from_url(cls, url):
        parsed = urlparse(url)
        if parsed.scheme != 'postgresql':
            raise ValueError("Unsupported scheme: {0}".format(parsed.scheme))

        dbconf = {
            'database': parsed.path.split('/')[1],
            'user': parsed.username,
            'password': parsed.password,
            'host': parsed.hostname,
            'port': parsed.port or 5432,
        }

        kwargs = {k: v[0] for k, v in parse_qs(parsed.query).iteritems()}

        return cls(dbconf, **kwargs)

    def __deepcopy__(self, memo):
        """
        The deepcopy is used when we want to use this guy in another thread /
        process / whatever. Since the psycopg2 connection is not thread-safe,
        we cannot share it -> instead, we do a copy.
        """
        return PostgreSQLStorage(self._dbconf, table_prefix=self._table_prefix)

    @property
    def db(self):
        if self._db is None or self._db.closed:
            self._db = self._connect()
        return self._db

    def _connect(self):
        conn = psycopg2.connect(**self._dbconf)
        conn.cursor_factory = psycopg2.extras.DictCursor
        conn.autocommit = False
        return conn

    def install(self):
        self._create_tables()

    def uninstall(self):
        self._drop_tables()

    def _create_tables(self):
        # ----------------------------------------------------------------------
        # Note: we use "TEXT" for the natural keys as there is no advantage
        #       in PostgreSQL (actually, TEXT is faster to write due to no
        #       need for length-constraint checking)
        # Note: Maybe there is a way to ask for a "full match" (hash table?)
        #       index only on the id field, thus speeding up things a bit?
        #       Anyways, we won't have a large number of objects here, nor
        #       complex joins, so there should be no problem at all..
        # ----------------------------------------------------------------------

        query = """
        CREATE TABLE "{prefix}build" (
            id SERIAL PRIMARY KEY,

            -- Configuration
            job_id TEXT,
            config BYTEA,

            -- State
            start_time TIMESTAMP WITHOUT TIME ZONE,
            end_time TIMESTAMP WITHOUT TIME ZONE,
            started BOOLEAN DEFAULT false,
            finished BOOLEAN DEFAULT false,
            success BOOLEAN DEFAULT false,
            skipped BOOLEAN DEFAULT false,
            retval BYTEA,
            exception BYTEA,
            exception_tb BYTEA
        );

        CREATE TABLE "{prefix}build_progress" (
            build_id INTEGER NOT NULL
                REFERENCES "{prefix}build" (id)
                ON DELETE CASCADE,
            group_name TEXT[] NOT NULL,
            current INTEGER NOT NULL,
            total INTEGER NOT NULL,
            status_line TEXT,
            UNIQUE (build_id, group_name)
        );

        CREATE TABLE "{prefix}log" (
            id SERIAL PRIMARY KEY,
            build_id INTEGER NOT NULL
                REFERENCES "{prefix}build" (id)
                ON DELETE CASCADE,
            created TIMESTAMP WITHOUT TIME ZONE,
            level INTEGER,
            record BYTEA
        );
        """.format(prefix=self._table_prefix)

        with self.db, self.db.cursor() as cur:
            cur.execute(query)

    def _drop_tables(self):
        names = ('build', 'build_progress', 'log')
        table_names = [self._table_name(x) for x in names]
        with self.db, self.db.cursor() as cur:
            for table in reversed(table_names):
                cur.execute('DROP TABLE "{name}" CASCADE;'.format(name=table))

    def _table_name(self, name):
        return '{0}{1}'.format(self._table_prefix, name)

    def _escape_name(self, name):
        """Escape a name for use as field name"""
        return '"{0}"'.format(name)

    # -------------------- Query building --------------------

    def _query_insert(self, table, data, returning='id'):
        _fields = sorted(data)
        query = """
        INSERT INTO "{table}" ({fields}) VALUES ({valspec})
        """.format(
            table=self._table_name(table),
            fields=', '.join(self._escape_name(x) for x in _fields),
            valspec=', '.join('%({0})s'.format(x) for x in _fields))
        if returning:
            query += ' RETURNING ' + returning
        query += ";"
        return query

    def _query_update(self, table, data, keys=None):
        _fields = [x for x in sorted(data) if x != 'id']

        if keys is None:
            keys = ['id']

        if isinstance(keys, basestring):
            keys = [keys]

        if not isinstance(keys, (tuple, list)):
            raise TypeError("Keys must be a tuple or list")

        if len(keys) < 1:
            raise TypeError('You must specify at least one key for update')

        where_clause = []
        for k in keys:
            where_clause.append('"{0}"=%({0})s'.format(k))
        where_clause = ' AND '.join(where_clause)

        return """
        UPDATE "{table}" SET {updates} WHERE {where_clause};
        """.format(
            table=self._table_name(table),
            updates=', '.join(
                "{0}=%({1})s".format(self._escape_name(fld), fld)
                for fld in _fields),
            where_clause=where_clause)

    def _query_select_one(self, table, fields='*'):
        return """
        SELECT {fields} FROM "{table}" WHERE "id"=%(id)s;
        """.format(table=self._table_name(table),
                   fields=fields)

    def _query_delete_one(self, table):
        return """
        DELETE FROM "{table}" WHERE "id"=%(id)s;
        """.format(table=self._table_name(table))

    def _query_select(self, table, fields='*', filters=None, order=None,
                      offset=None, limit=None):

        query_parts = ["SELECT {0} FROM {1}".format(
            fields, self._table_name(table))]

        if filters is not None:
            query_parts.append('WHERE {0}'.format(' AND '.join(filters)))

        if order is not None:
            if not isinstance(order, basestring):
                order = ', '.join(order)
            query_parts.append('ORDER BY {0}'.format(order))

        if offset is not None:
            query_parts.append('OFFSET {0}'.format(int(offset)))

        if limit is not None:
            query_parts.append('LIMIT {0}'.format(int(limit)))

        return ' '.join(query_parts) + ';'

    # -------------------- Query running --------------------

    def _do_insert(self, table, data, returning='id'):
        query = self._query_insert(table, data, returning=returning)
        with self.db, self.db.cursor() as cur:
            cur.execute(query, data)
            if returning:
                return cur.fetchone()[0]

    def _do_update(self, table, data, keys=None):
        query = self._query_update(table, data, keys=keys)
        with self.db, self.db.cursor() as cur:
            cur.execute(query, data)

    def _do_select_one(self, table, pk):
        query = self._query_select_one(table)
        with self.db, self.db.cursor() as cur:
            cur.execute(query, {'id': pk})
            return cur.fetchone()

    def _do_delete_one(self, table, pk):
        query = self._query_delete_one(table)
        with self.db, self.db.cursor() as cur:
            cur.execute(query, {'id': pk})

    def _do_select(self, table, **kw):
        query = self._query_select(table, **kw)
        with self.db, self.db.cursor() as cur:
            cur.execute(query)
            for item in cur.fetchall():
                yield item

    # -------------------- Object serialization --------------------

    def _convert_object(self, obj, mapping):
        for key, val in mapping.iteritems():
            if obj.get(key) is not None:
                obj[key] = val(obj[key])
        return obj

    def _build_pack(self, build):
        mapping = {
            'retval': lambda x: buffer(self.pack(x, safe=True)),
            'exception': lambda x: buffer(self.pack_exception(x)),
            'exception_tb': lambda x: buffer(self.pack(x, safe=True)),
            'config': lambda x: buffer(self.pack(x, safe=False)),
        }
        return self._convert_object(build, mapping)

    def _build_unpack(self, row):
        row = dict(row)
        mapping = {
            'retval': lambda x: self.unpack(x, safe=True),
            'exception': lambda x: self.unpack(x, safe=True),
            'exception_tb': lambda x: self.unpack(x, safe=True),
            'config': lambda x: self.unpack(x, safe=False),
        }
        return self._normalize_build_info(self._convert_object(row, mapping))

    def get_job_builds(self, job_id, started=None, finished=None,
                       success=None, skipped=None, order='asc', limit=100):
        """
        Get all the builds for a job, sorted by date, according
        to the order specified by ``order``.

        :param job_id:
            The job id

        :param started:
            If set to a boolean, filter on the "started" field

        :param finished:
            If set to a boolean, filter on the "finished" field

        :param success:
            If set to a boolean, filter on the "success" field

        :param skipped:
            If set to a boolean, filter on the "skipped" field

        :param order:
            'asc' (default) or 'desc'

        :param limit:
            only return the first ``limit`` builds
        """

        wheres = ['"job_id"=%(job_id)s']
        data = {'job_id': job_id}

        filters = [
            ('started', started),
            ('finished', finished),
            ('success', success),
            ('skipped', skipped),
        ]

        for key, val in filters:
            if val is not None:
                wheres.append('"{0}"=%({0})s'.format(key))
                data[key] = val

        query = "SELECT * FROM {table} WHERE {wheres}".format(
            table=self._table_name('build'),
            wheres=' AND '.join(wheres))

        order = order.lower()

        if order == 'asc':
            query += ' ORDER BY id ASC'

        elif order == 'desc':
            query += ' ORDER BY id DESC'

        else:
            raise ValueError("Invalid order direction: {0}".format(order))

        if limit is not None:
            query += ' LIMIT %(limit)s'
            data['limit'] = limit

        query += ';'

        with self.db, self.db.cursor() as cur:
            cur.execute(query, data)
            for x in cur.fetchall():
                yield self._build_unpack(x)

    # ------------------------------------------------------------
    # Build CRUD methods
    # ------------------------------------------------------------

    def create_build(self, job_id, config=None):
        return self._do_insert('build', self._build_pack({
            'job_id': job_id,
            'config': config or {},
        }))

    def get_build(self, build_id):
        build = self._do_select_one('build', build_id)
        if build is None:
            raise NotFound('Build not found: {0}'.format(build_id))
        return self._build_unpack(build)

    def delete_build(self, build_id):
        self._do_delete_one('build', build_id)

    def start_build(self, build_id):
        self._do_update('build', {
            'id': build_id,
            'start_time': datetime.now(),
            'started': True,
        })

    def finish_build(self, build_id, success=True, skipped=False, retval=None,
                     exception=None, exception_tb=None):

        self._do_update('build', self._build_pack({
            'id': build_id,
            'end_time': datetime.now(),
            'finished': True,
            'success': success,
            'skipped': skipped,
            'retval': retval,
            'exception': exception,
            'exception_tb': exception_tb,
        }))

    def report_build_progress(self, build_id, current, total, group_name=None,
                              status_line=''):

        """
        We need to "upsert" the record in PostgreSQL build_progress table.
        Since no deletions should happen, we can safely:

        - INSERT -> on constraint violation -> UPDATE
        """

        if not isinstance(current, (int, long)):
            raise TypeError('Progress "current" must be an integer')

        if not isinstance(total, (int, long)):
            raise TypeError('Progress "total" must be an integer')

        if not group_name:
            group_name = None

        if group_name is not None:
            if isinstance(group_name, tuple):
                # We need it to be a list in order for psycopg2
                # to adapt this to the correct TEXT[] type.
                group_name = list(group_name)

            if not isinstance(group_name, list):
                raise TypeError('group_name must be a list / tuple (or None)')

        record = {
            'build_id': build_id,
            'current': current,
            'total': total,
            'group_name': group_name or [],
            'status_line': status_line,
        }

        try:
            self._do_insert('build_progress', record, returning=None)
        except psycopg2.IntegrityError:
            self._do_update('build_progress', record,
                            keys=('build_id', 'group_name'))

    def get_build_progress_info(self, build_id):
        query = 'SELECT * FROM "{0}" WHERE build_id = %(id)s;'.format(
            self._table_name('build_progress'))

        items = []
        with self.db, self.db.cursor() as cur:
            cur.execute(query, {'id': build_id})
            for row in cur.fetchall():
                items.append((
                    row['group_name'],
                    row['current'], row['total'],
                    row['status_line']))
        return items

    def log_message(self, build_id, record):
        record = self._prepare_log_record(record)
        record['build_id'] = build_id

        row = {
            'build_id': record.build_id,
            'record': buffer(self.pack(record)),
            'created': record.created,
            'level': record.level,
        }

        self._do_insert('log', row)

    def prune_log_messages(self, build_id=None, max_age=None, level=None):
        """
        Delete old log messages.

        :param build_id:
            If specified, only delete messages for this build

        :param max_age:
            If specified, only delete log messages with an age
            greater than this one (in seconds)

        :param level:
            If specified, only delete log messages with a level
            equal minor to this one
        """

        conditions = []
        filters = {}

        if build_id is not None:
            conditions.append('"build_id"=%(build_id)s')
            filters['build_id'] = build_id

        if max_age is not None:
            expire_date = datetime.now() - timedelta(seconds=max_age)
            conditions.append('"created" < %(expire_date)s')
            filters['expire_date'] = expire_date

        if level is not None:
            conditions.append('"level" < %(level)s')
            filters['level'] = level

        query = 'DELETE FROM "{0}"'.format(self._table_name('log'))

        if len(conditions) > 0:
            query += ' WHERE {0}'.format(' AND '.join(conditions))

        query += ';'

        with self.db, self.db.cursor() as cur:
            cur.execute(query, filters)

    def iter_log_messages(self, build_id=None, max_date=None,
                          min_date=None, min_level=None):

        conditions = []
        filters = {}

        if build_id is not None:
            conditions.append('"build_id"=%(build_id)s')
            filters['build_id'] = build_id

        if max_date is not None:
            conditions.append('"created" < %(max_date)s')
            filters['max_date'] = max_date

        if min_date is not None:
            conditions.append('"created" >= %(min_date)s')
            filters['min_date'] = min_date

        if min_level is not None:
            conditions.append('"level" >= %(min_level)s')
            filters['min_level'] = min_level

        query = 'SELECT * FROM "{0}"'.format(self._table_name('log'))

        if len(conditions) > 0:
            query += ' WHERE {0}'.format(' AND '.join(conditions))

        query += ' ORDER BY created ASC'

        query += ';'

        with self.db, self.db.cursor() as cur:
            cur.execute(query, filters)
            for item in cur.fetchall():
                record = self.unpack(item['record'])
                yield record
