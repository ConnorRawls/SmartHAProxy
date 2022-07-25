/*
 * Fast Weighted Least Connection load balancing algorithm.
 *
 * Copyright 2000-2009 Willy Tarreau <w@1wt.eu>
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version
 * 2 of the License, or (at your option) any later version.
 *
 */

#include <import/eb32tree.h>
#include <haproxy/api.h>
#include <haproxy/backend.h>
#include <haproxy/queue.h>
#include <haproxy/server-t.h>

///////////////// Begin edits /////////////////
#include <haproxy/whitelist.h>
#include <time.h>
#include <pthread.h>

#define SRVCOUNT 7
#define MAX_LINE 1024

ReqCount reqCount;
Lock check;

////////////////// End edits //////////////////


/* Remove a server from a tree. It must have previously been dequeued. This
 * function is meant to be called when a server is going down or has its
 * weight disabled.
 *
 * The server's lock and the lbprm's lock must be held.
 */
static inline void fwlc_remove_from_tree(struct server *s)
{
	s->lb_tree = NULL;
}

/* simply removes a server from a tree.
 *
 * The lbprm's lock must be held.
 */
static inline void fwlc_dequeue_srv(struct server *s)
{
	eb32_delete(&s->lb_node);
}

/* Queue a server in its associated tree, assuming the <eweight> is >0.
 * Servers are sorted by (#conns+1)/weight. To ensure maximum accuracy,
 * we use (#conns+1)*SRV_EWGHT_MAX/eweight as the sorting key. The reason
 * for using #conns+1 is to sort by weights in case the server is picked
 * and not before it is picked. This provides a better load accuracy for
 * low connection counts when weights differ and makes sure the round-robin
 * applies between servers of highest weight first. However servers with no
 * connection are always picked first so that under low loads, it's not
 * always the single server with the highest weight that gets picked.
 *
 * NOTE: Depending on the calling context, we use s->next_eweight or
 *       s->cur_eweight. The next value is used when the server state is updated
 *       (because the weight changed for instance). During this step, the server
 *       state is not yet committed. The current value is used to reposition the
 *       server in the tree. This happens when the server is used.
 *
 * The lbprm's lock must be held.
 */
static inline void fwlc_queue_srv(struct server *s, unsigned int eweight)
{
	unsigned int inflight = _HA_ATOMIC_LOAD(&s->served) + _HA_ATOMIC_LOAD(&s->queue.length);

	s->lb_node.key = inflight ? (inflight + 1) * SRV_EWGHT_MAX / eweight : 0;
	eb32_insert(s->lb_tree, &s->lb_node);
}

/* Re-position the server in the FWLC tree after it has been assigned one
 * connection or after it has released one. Note that it is possible that
 * the server has been moved out of the tree due to failed health-checks.
 * The lbprm's lock will be used.
 */
static void fwlc_srv_reposition(struct server *s)
{
	unsigned int inflight = _HA_ATOMIC_LOAD(&s->served) + _HA_ATOMIC_LOAD(&s->queue.length);
	unsigned int new_key = inflight ? (inflight + 1) * SRV_EWGHT_MAX / s->cur_eweight : 0;

	/* some calls will be made for no change (e.g connect_server() after
	 * assign_server(). Let's check that first.
	 */
	if (s->lb_node.node.leaf_p && s->lb_node.key == new_key)
		return;

	HA_RWLOCK_WRLOCK(LBPRM_LOCK, &s->proxy->lbprm.lock);
	if (s->lb_tree) {
		/* we might have been waiting for a while on the lock above
		 * so it's worth testing again because other threads are very
		 * likely to have released a connection or taken one leading
		 * to our target value (50% of the case in measurements).
		 */
		inflight = _HA_ATOMIC_LOAD(&s->served) + _HA_ATOMIC_LOAD(&s->queue.length);
		new_key = inflight ? (inflight + 1) * SRV_EWGHT_MAX / s->cur_eweight : 0;
		if (!s->lb_node.node.leaf_p || s->lb_node.key != new_key) {
			eb32_delete(&s->lb_node);
			s->lb_node.key = new_key;
			eb32_insert(s->lb_tree, &s->lb_node);
		}
	}
	HA_RWLOCK_WRUNLOCK(LBPRM_LOCK, &s->proxy->lbprm.lock);
}

/* This function updates the server trees according to server <srv>'s new
 * state. It should be called when server <srv>'s status changes to down.
 * It is not important whether the server was already down or not. It is not
 * important either that the new state is completely down (the caller may not
 * know all the variables of a server's state).
 *
 * The server's lock must be held. The lbprm's lock will be used.
 */
static void fwlc_set_server_status_down(struct server *srv)
{
	struct proxy *p = srv->proxy;

	if (!srv_lb_status_changed(srv))
		return;

	if (srv_willbe_usable(srv))
		goto out_update_state;
	HA_RWLOCK_WRLOCK(LBPRM_LOCK, &p->lbprm.lock);


	if (!srv_currently_usable(srv))
		/* server was already down */
		goto out_update_backend;

	if (srv->flags & SRV_F_BACKUP) {
		p->lbprm.tot_wbck -= srv->cur_eweight;
		p->srv_bck--;

		if (srv == p->lbprm.fbck) {
			/* we lost the first backup server in a single-backup
			 * configuration, we must search another one.
			 */
			struct server *srv2 = p->lbprm.fbck;
			do {
				srv2 = srv2->next;
			} while (srv2 &&
				 !((srv2->flags & SRV_F_BACKUP) &&
				   srv_willbe_usable(srv2)));
			p->lbprm.fbck = srv2;
		}
	} else {
		p->lbprm.tot_wact -= srv->cur_eweight;
		p->srv_act--;
	}

	fwlc_dequeue_srv(srv);
	fwlc_remove_from_tree(srv);

out_update_backend:
	/* check/update tot_used, tot_weight */
	update_backend_weight(p);
	HA_RWLOCK_WRUNLOCK(LBPRM_LOCK, &p->lbprm.lock);

 out_update_state:
	srv_lb_commit_status(srv);
}

/* This function updates the server trees according to server <srv>'s new
 * state. It should be called when server <srv>'s status changes to up.
 * It is not important whether the server was already down or not. It is not
 * important either that the new state is completely UP (the caller may not
 * know all the variables of a server's state). This function will not change
 * the weight of a server which was already up.
 *
 * The server's lock must be held. The lbprm's lock will be used.
 */
static void fwlc_set_server_status_up(struct server *srv)
{
	struct proxy *p = srv->proxy;

	if (!srv_lb_status_changed(srv))
		return;

	if (!srv_willbe_usable(srv))
		goto out_update_state;

	HA_RWLOCK_WRLOCK(LBPRM_LOCK, &p->lbprm.lock);

	if (srv_currently_usable(srv))
		/* server was already up */
		goto out_update_backend;

	if (srv->flags & SRV_F_BACKUP) {
		srv->lb_tree = &p->lbprm.fwlc.bck;
		p->lbprm.tot_wbck += srv->next_eweight;
		p->srv_bck++;

		if (!(p->options & PR_O_USE_ALL_BK)) {
			if (!p->lbprm.fbck) {
				/* there was no backup server anymore */
				p->lbprm.fbck = srv;
			} else {
				/* we may have restored a backup server prior to fbck,
				 * in which case it should replace it.
				 */
				struct server *srv2 = srv;
				do {
					srv2 = srv2->next;
				} while (srv2 && (srv2 != p->lbprm.fbck));
				if (srv2)
					p->lbprm.fbck = srv;
			}
		}
	} else {
		srv->lb_tree = &p->lbprm.fwlc.act;
		p->lbprm.tot_wact += srv->next_eweight;
		p->srv_act++;
	}

	/* note that eweight cannot be 0 here */
	fwlc_queue_srv(srv, srv->next_eweight);

 out_update_backend:
	/* check/update tot_used, tot_weight */
	update_backend_weight(p);
	HA_RWLOCK_WRUNLOCK(LBPRM_LOCK, &p->lbprm.lock);

 out_update_state:
	srv_lb_commit_status(srv);
}

/* This function must be called after an update to server <srv>'s effective
 * weight. It may be called after a state change too.
 *
 * The server's lock must be held. The lbprm's lock will be used.
 */
static void fwlc_update_server_weight(struct server *srv)
{
	int old_state, new_state;
	struct proxy *p = srv->proxy;

	if (!srv_lb_status_changed(srv))
		return;

	/* If changing the server's weight changes its state, we simply apply
	 * the procedures we already have for status change. If the state
	 * remains down, the server is not in any tree, so it's as easy as
	 * updating its values. If the state remains up with different weights,
	 * there are some computations to perform to find a new place and
	 * possibly a new tree for this server.
	 */
	 
	old_state = srv_currently_usable(srv);
	new_state = srv_willbe_usable(srv);

	if (!old_state && !new_state) {
		srv_lb_commit_status(srv);
		return;
	}
	else if (!old_state && new_state) {
		fwlc_set_server_status_up(srv);
		return;
	}
	else if (old_state && !new_state) {
		fwlc_set_server_status_down(srv);
		return;
	}

	HA_RWLOCK_WRLOCK(LBPRM_LOCK, &p->lbprm.lock);

	if (srv->lb_tree)
		fwlc_dequeue_srv(srv);

	if (srv->flags & SRV_F_BACKUP) {
		p->lbprm.tot_wbck += srv->next_eweight - srv->cur_eweight;
		srv->lb_tree = &p->lbprm.fwlc.bck;
	} else {
		p->lbprm.tot_wact += srv->next_eweight - srv->cur_eweight;
		srv->lb_tree = &p->lbprm.fwlc.act;
	}

	fwlc_queue_srv(srv, srv->next_eweight);

	update_backend_weight(p);
	HA_RWLOCK_WRUNLOCK(LBPRM_LOCK, &p->lbprm.lock);

	srv_lb_commit_status(srv);
}

/* This function is responsible for building the trees in case of fast
 * weighted least-conns. It also sets p->lbprm.wdiv to the eweight to
 * uweight ratio. Both active and backup groups are initialized.
 */
void fwlc_init_server_tree(struct proxy *p)
{
	struct server *srv;
	struct eb_root init_head = EB_ROOT;

	p->lbprm.set_server_status_up   = fwlc_set_server_status_up;
	p->lbprm.set_server_status_down = fwlc_set_server_status_down;
	p->lbprm.update_server_eweight  = fwlc_update_server_weight;
	p->lbprm.server_take_conn = fwlc_srv_reposition;
	p->lbprm.server_drop_conn = fwlc_srv_reposition;

	p->lbprm.wdiv = BE_WEIGHT_SCALE;
	for (srv = p->srv; srv; srv = srv->next) {
		srv->next_eweight = (srv->uweight * p->lbprm.wdiv + p->lbprm.wmult - 1) / p->lbprm.wmult;
		srv_lb_commit_status(srv);
	}

	recount_servers(p);
	update_backend_weight(p);

	p->lbprm.fwlc.act = init_head;
	p->lbprm.fwlc.bck = init_head;

	/* queue active and backup servers in two distinct groups */
	for (srv = p->srv; srv; srv = srv->next) {
		if (!srv_currently_usable(srv))
			continue;
		srv->lb_tree = (srv->flags & SRV_F_BACKUP) ? &p->lbprm.fwlc.bck : &p->lbprm.fwlc.act;
		fwlc_queue_srv(srv, srv->next_eweight);
	}
}

///////////////// Begin edits /////////////////

/* Return next server from the FWLC tree in backend <p>. If the tree is empty,
 * return NULL. Saturated servers are skipped.
 *
 * The lbprm's lock will be used in R/O mode. The server's lock is not used.
 */
struct server *fwlc_get_next_server(struct proxy *p, struct server *srvtoavoid, int method_key, const char *uri, int uri_len)
{
	struct server *srv, *avoided;
	struct eb32_node *node;
	char *url_cpy; //url extracted from the uri
	char *qry_cpy;
	const char *url; //pointer to where the url ends
	char *servers; //list of servers from the whitelist that the request url can use
	int url_len; //length of url string
	int qry_len;
	char *method_name;
	int method_length;
	clock_t t2;
	double elapsed_time;
	char key[MAX_LINE] = "";
	char *buffer;
	char srv_num;
	srv_num = 0;

	srv = avoided = NULL;

	// Update Whitelist
	pthread_mutex_lock(&check.lock);

	t2 = clock();
	elapsed_time = howLong(reqCount.time, t2);
	reqCount.count++;

	if(reqCount.count == 10000 || elapsed_time >= (double)2){
		printf("\nUpdating whitelist.\n");
		updateWhitelist();

		reqCount.time = clock();
		reqCount.count = 0;
	}

	pthread_mutex_unlock(&check.lock);

	// Method
	switch (method_key) {
		case 1:
			method_length = sizeof("GET") + 1;
			method_name = malloc(sizeof(char) * method_length);
			strncpy(method_name, "GET", method_length);
			method_name[method_length] = '\0';
			break;
		case 3:
			method_length = sizeof("POST") + 1;
			method_name = malloc(sizeof(char) * method_length);
			strncpy(method_name, "POST", method_length);
			method_name[method_length] = '\0';
			break;
		default:
			method_length = 0;
			method_name = NULL;
			break;
	}

	// URL + Query
	url_len = uri_len;
	qry_len = uri_len;
	if((url = memchr(uri, '?', uri_len)) != NULL){ // if ? is found in the url
		url_len = url - uri;
		qry_len = uri_len - url_len;
		qry_cpy = malloc(sizeof(char) * (qry_len + 1));
		strncpy(qry_cpy, url, qry_len);
		qry_cpy[qry_len] = '\0';
	} else {
		qry_len = sizeof("NULL");
		qry_cpy = malloc(sizeof(char) * (qry_len + 1));
		strcpy(qry_cpy, "NULL");
		qry_cpy[qry_len] = '\0';
	}

	url_cpy = malloc(sizeof(char) * (uri_len + 1));
	strncpy(url_cpy, uri, url_len);
	url_cpy[url_len] = '\0'; //adds an ending \0 (null character)

	if(!strcmp(url_cpy, "/wp-profiling/")) {
		free(url_cpy);
		buffer = malloc(sizeof("/wp-profiling/index.php"));
		strcpy(buffer, "/wp-profiling/index.php");
		url_cpy = buffer;
	}

	// Search for task's WL
	strcat(strcat(strcat(key, method_name), url_cpy), qry_cpy);
	servers = NULL;
	servers = searchRequest(key);
	if(servers != NULL) strcat(servers, "\0");
	if(strchr(servers, '0') != NULL) return NULL;

	// We're freeeeeee
	free(method_name);
	free(url_cpy);
	free(qry_cpy);

	HA_RWLOCK_RDLOCK(LBPRM_LOCK, &p->lbprm.lock);
	if (p->srv_act)
		node = eb32_first(&p->lbprm.fwlc.act);
	else if (p->lbprm.fbck) {
		srv = p->lbprm.fbck;
		goto out;
	}
	else if (p->srv_bck)
		node = eb32_first(&p->lbprm.fwlc.bck);
	else {
		srv = NULL;
		goto out;
	}

	while (node) {
		/* OK, we have a server. However, it may be saturated, in which
		 * case we don't want to reconsider it for now, so we'll simply
		 * skip it. Same if it's the server we try to avoid, in which
		 * case we simply remember it for later use if needed.
		 */
		struct server *s;

		s = eb32_entry(node, struct server, lb_node);
		if(s == NULL || s->id == NULL) srv_num = '0';
		else if(strcmp(s->id, "WP-Host") == 0) srv_num = '1';
		else srv_num = s->id[strlen(s->id) - 1];
		if (!s->maxconn || s->served + s->queue.length < srv_dynamic_maxconn(s) + s->maxqueue) {
			if (s != srvtoavoid || strchr(servers, srv_num) != NULL) {
				srv = s;
				break;
			}
			avoided = s;
		}
		node = eb32_next(node);
	}

	if (!srv)
		srv = avoided;
 out:
	HA_RWLOCK_RDUNLOCK(LBPRM_LOCK, &p->lbprm.lock);

	if(servers != NULL) logDispatch(key, servers, srv_num);

	return srv;
}

////////////////// End edits //////////////////

/*
 * Local variables:
 *  c-indent-level: 8
 *  c-basic-offset: 8
 * End:
 */
