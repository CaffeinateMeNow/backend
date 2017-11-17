package MediaWords::Test::DB;

# database utility functions for testing.  includes functionality to run tests on a temporary db

use strict;
use warnings;

use Modern::Perl "2015";
use MediaWords::CommonLibs;

use File::Path;
use Readonly;
use Text::Lorem::More;

use MediaWords::DB;
use MediaWords::DBI::Auth;
use MediaWords::DBI::Downloads;
use MediaWords::Job::ExtractAndVector;
use MediaWords::DB::Schema;
use MediaWords::Util::Config;
use MediaWords::Util::URL;

{

    package MediaWords::Test::DB::PythonProxy;

    #
    # Proxy to mediawords.test.db; used to make return values editable
    #

    use strict;
    use warnings;

    use Modern::Perl "2015";
    use MediaWords::CommonLibs;

    import_python_module( __PACKAGE__, 'mediawords.test.db' );

    1;
}

sub force_using_test_database()
{
    MediaWords::Test::DB::PythonProxy::force_using_test_database();
}

sub using_test_database()
{
    return MediaWords::Test::DB::PythonProxy::using_test_database();
}

sub create_download_for_feed($$)
{
    my ( $db, $feed ) = @_;

    my $return_value = MediaWords::Test::DB::PythonProxy::create_download_for_feed( $db, $feed );
    return python_deep_copy( $return_value );
}

sub create_test_medium($$)
{
    my ( $db, $label ) = @_;

    my $return_value = MediaWords::Test::DB::PythonProxy::create_test_medium( $db, $label );
    return python_deep_copy( $return_value );
}

sub create_test_feed($$$)
{
    my ( $db, $label, $medium ) = @_;

    my $return_value = MediaWords::Test::DB::PythonProxy::create_test_feed( $db, $label, $medium );
    return python_deep_copy( $return_value );
}

sub create_test_story($$$)
{
    my ( $db, $label, $feed ) = @_;

    my $return_value = MediaWords::Test::DB::PythonProxy::create_test_story( $db, $label, $feed );
    return python_deep_copy( $return_value );
}

sub create_test_story_stack($$)
{
    my ( $db, $data ) = @_;

    my $return_value = MediaWords::Test::DB::PythonProxy::create_test_story_stack( $db, $data );
    return python_deep_copy( $return_value );
}

sub create_test_story_stack_numerated($$$$;$)
{
    my ( $db, $num_media, $num_feeds_per_medium, $num_stories_per_feed, $label ) = @_;

    my $return_value =
      MediaWords::Test::DB::PythonProxy::create_test_story_stack_numerated( $db, $num_media, $num_feeds_per_medium,
        $num_stories_per_feed, $label );
    return python_deep_copy( $return_value );
}

sub create_test_topic($$)
{
    my ( $db, $label ) = @_;

    my $return_value = MediaWords::Test::DB::PythonProxy::create_test_topic( $db, $label );
    return python_deep_copy( $return_value );
}

# run the given function on a temporary, clean database
sub test_on_test_database
{
    my ( $sub ) = @_;

    MediaWords::DB::Schema::recreate_db( 'test' );

    my $db = MediaWords::DB::connect_to_db( 'test' );

    force_using_test_database();

    eval { $sub->( $db ); };

    if ( $@ )
    {
        die( $@ );
    }

    if ( $db )
    {
        $db->disconnect();
    }
}

# generated 1 - 10 paragraphs of 1 - 5 sentences of ipsem lorem.
sub _get_test_content
{
    my $lorem = Text::Lorem::More->new();

    my $num_paragraphs = int( rand( 10 ) + 1 );

    my $paragraphs = [];

    for my $i ( 1 .. $num_paragraphs )
    {
        my $text = $lorem->sentences( int( rand( 5 ) + 1 ) );
        push( @{ $paragraphs }, $text );
    }

    my $content = join( "\n\n", map { "<p>\n$_\n</p>" } @{ $paragraphs } );

    return $content;
}

# adds a 'download' and a 'content' field to each story in the test story stack.  stores the content in the download
# store.  generates the content using _get_test_content()
sub add_content_to_test_story($$$)
{
    my ( $db, $story, $feed ) = @_;

    my $content = _get_test_content();

    if ( $story->{ full_text_rss } )
    {
        $story->{ full_text_rss } = 0;
        $db->update_by_id( 'stories', $story->{ stories_id }, { full_text_rss => 'f' } );
    }

    my $host     = MediaWords::Util::URL::get_url_host( $feed->{ url } );
    my $download = $db->create(
        'downloads',
        {
            feeds_id      => $feed->{ feeds_id },
            url           => $story->{ url },
            host          => $host,
            type          => 'content',
            sequence      => 1,
            state         => 'fetching',
            priority      => 1,
            download_time => 'now()',
            extracted     => 'f',
            stories_id    => $story->{ stories_id }
        }
    );

    $download = MediaWords::DBI::Downloads::store_content( $db, $download, \$content );

    $story->{ download } = $download;
    $story->{ content }  = $content;

    MediaWords::Job::ExtractAndVector->run( { stories_id => $story->{ stories_id } } );

    $story->{ download_text } = $db->query( <<SQL, $download->{ downloads_id } )->hash;
select * from download_texts where downloads_id = ?
SQL

    die( "Unable to find download_text" ) unless ( $story->{ download_text } );
}

# add a download and store its content for each story in the test story stack as returned from create_test_story_stack.
# also extract and vector each download.
sub add_content_to_test_story_stack($$)
{
    my ( $db, $story_stack ) = @_;

    DEBUG( "adding content to test story stack ..." );

    for my $medium ( values( %{ $story_stack } ) )
    {
        for my $feed ( values( %{ $medium->{ feeds } } ) )
        {
            for my $story ( values( %{ $feed->{ stories } } ) )
            {
                add_content_to_test_story( $db, $story, $feed );
            }
        }
    }
}

# Create a user for temporary databases
sub create_test_user($$)
{
    my ( $db, $label ) = @_;

    my $email = $label . '@em.ail';

    eval {
        my $new_user = MediaWords::DBI::Auth::User::NewUser->new(
            email           => $email,
            full_name       => $label,
            notes           => '',
            role_ids        => [ 1 ],
            active          => 1,
            password        => 'testtest',
            password_repeat => 'testtest',
            activation_url  => '',           # user is active, no need for activation URL
        );

        MediaWords::DBI::Auth::Register::add_user( $db, $new_user );
    };
    if ( $@ )
    {
        LOGCONFESS "Adding new user failed: $@";
    }

    my $user_info = MediaWords::DBI::Auth::Profile::user_info( $db, $email );
    my $api_key = $user_info->global_api_key();

    return $api_key;
}

1;
