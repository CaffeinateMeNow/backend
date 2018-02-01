package MediaWords::Controller::Api::V2::Topics::Snapshots;
use Modern::Perl "2015";
use MediaWords::CommonLibs;

use strict;
use warnings;
use base 'Catalyst::Controller';
use Moose;
use namespace::autoclean;

use MediaWords::Job::TM::SnapshotTopic;

BEGIN { extends 'MediaWords::Controller::Api::V2::MC_Controller_REST' }

__PACKAGE__->config(
    action => {
        list            => { Does => [ qw( ~TopicsReadAuthenticated ~Throttled ~Logged ) ] },
        generate        => { Does => [ qw( ~TopicsWriteAuthenticated ~Throttled ~Logged ) ] },
        generate_status => { Does => [ qw( ~TopicsReadAuthenticated ~Throttled ~Logged ) ] },
    }
);

Readonly my $JOB_STATE_FIELD_LIST =>
"job_states_id, ( args->>'topics_id' )::int topics_id, ( args->>'snapshots_id' )::int snapshots_id, state, message, last_updated";

sub apibase : Chained('/') : PathPart('api/v2/topics') : CaptureArgs(1)
{
    my ( $self, $c, $topics_id ) = @_;
    $c->stash->{ topics_id } = int( $topics_id );
}

sub snapshots : Chained('apibase') : PathPart('snapshots') : CaptureArgs(1)
{
    my ( $self, $c, $snapshots_id ) = @_;
    $c->stash->{ snapshots_id } = int( $snapshots_id );
}

sub list : Chained('apibase') : PathPart( 'snapshots/list' ) : Args(0) : ActionClass('MC_REST')
{

}

sub list_GET
{
    my ( $self, $c ) = @_;

    my $db = $c->dbis;

    my $topics_id = $c->stash->{ topics_id };

    my $snapshots = $db->query(
        <<SQL,
        SELECT
            snapshots_id,
            snapshot_date,
            note,
            state,
            searchable,
            message
        FROM snapshots
        WHERE topics_id = \$1
        ORDER BY snapshots_id DESC
SQL
        $topics_id
    )->hashes;

    $snapshots = $db->attach_child_query(
        $snapshots, <<SQL,
        SELECT
            word2vec_models_id AS models_id,

            -- FIXME snapshots_id gets into resulting hashes, not sure how to
            -- get rid of it with attach_child_query()
            object_id AS snapshots_id,

            creation_date
        FROM snap.word2vec_models
SQL
        'word2vec_models', 'snapshots_id'
    );

    $self->status_ok( $c, entity => { snapshots => $snapshots } );
}

sub generate : Chained('apibase') : PathPart( 'snapshots/generate' ) : Args(0) : ActionClass('MC_REST')
{
}

sub generate_GET
{
    my ( $self, $c ) = @_;

    my $topics_id = $c->stash->{ topics_id };

    my $note = $c->req->data->{ post } || '' if ( $c->req->data );

    my $job_class = MediaWords::Job::TM::SnapshotTopic->name;

    my $db = $c->dbis;

    my $job_state = $db->query( <<SQL, $topics_id, $job_class )->hash;
select $JOB_STATE_FIELD_LIST
    from pending_job_states
    where
        ( args->>'topics_id' )::int = \$1 and
        class = \$2
    order by job_states_id desc
SQL

    if ( !$job_state )
    {
        $db->begin;
        MediaWords::Job::TM::SnapshotTopic->add_to_queue( { topics_id => $topics_id, note => $note }, undef, $db );
        $job_state = $db->query( "select $JOB_STATE_FIELD_LIST from job_states order by job_states_id desc limit 1" )->hash;
        $db->commit;

        die( "Unable to find job state from queued job" ) unless ( $job_state );
    }

    return $self->status_ok( $c, entity => { job_state => $job_state } );
}

sub generate_status : Chained('apibase') : PathPart( 'snapshots/generate_status' ) : Args(0) : ActionClass('MC_REST')
{
}

sub generate_status_GET
{
    my ( $self, $c ) = @_;

    my $topics_id = $c->stash->{ topics_id };

    my $job_class = MediaWords::Job::TM::SnapshotTopic->name;

    my $db = $c->dbis;

    my $job_states;

    $job_states = $db->query( <<SQL, $topics_id, $job_class )->hashes;
select $JOB_STATE_FIELD_LIST
    from job_states
    where
        class = \$2 and
        ( args->>'topics_id' )::int = \$1
    order by last_updated desc
SQL

    $self->status_ok( $c, entity => { job_states => $job_states } );
}

1;
