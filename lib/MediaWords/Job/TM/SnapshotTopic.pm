package MediaWords::Job::TM::SnapshotTopic;

#
# Snapshot various topic queries to csv and build a gexf file
#
# Start this worker script by running:
#
# ./script/run_in_env.sh mjm_worker.pl lib/MediaWords/Job/TM/SnapshotTopic.pm
#

use strict;
use warnings;

use Moose;
with 'MediaWords::AbstractJob';

use Modern::Perl "2015";
use MediaWords::CommonLibs;

use MediaWords::TM::Snapshot;
use MediaWords::DB;

sub use_job_state
{
    return 1;
}

sub get_state_table_info
{
    return { table => 'snapshots', state => 'state', message => 'message' };
}

# Run job
sub run_statefully($$;$)
{
    my ( $self, $db, $args ) = @_;

    my $topics_id  = $args->{ topics_id };
    my $note       = $args->{ note };
    my $bot_policy = $args->{ bot_policy };
    my $periods    = $args->{ periods };
    my $skip_foci  = $args->{ skip_foci };

    die( "'topics_id' is undefined" ) unless ( defined $topics_id );

    # No transaction started because apparently snapshot_topic() does start one itself
    MediaWords::TM::Snapshot::snapshot_topic( $db, $topics_id, $note, $bot_policy, $periods, $skip_foci );
}

no Moose;    # gets rid of scaffolding

# Return package name instead of 1 or otherwise worker.pl won't know the name of the package it's loading
__PACKAGE__;
