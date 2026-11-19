/* Regression test for 'kern' table format 2 (class-based kerning).
 *
 * Covers correct value lookup, the coverage override/add semantics,
 * zero-regression of the format 0 path, and distinct failure codes for
 * truncated class tables versus out-of-bounds kerning indices.
 *
 * Distributed under the FreeType project license, LICENSE.TXT.
 */

#include <stdio.h>
#include <string.h>

#include <ft2build.h>
#include FT_FREETYPE_H
#include <freetype/internal/ftobjs.h>
#include <freetype/internal/sfnt.h>
#include <freetype/internal/tttypes.h>


  static FT_Library  library;


  static int
  check_kern( const char*  path,
              FT_UInt      left,
              FT_UInt      right,
              FT_Int       expected )
  {
    FT_Face     face = NULL;
    FT_Vector   vec;
    FT_Error    error;
    int         result = 1;


    error = FT_New_Face( library, path, 0, &face );
    if ( error )
    {
      fprintf( stderr, "FAIL %s: FT_New_Face error 0x%x\n", path, error );
      goto Exit;
    }

    if ( !FT_HAS_KERNING( face ) )
    {
      fprintf( stderr, "FAIL %s: kerning flag not set\n", path );
      goto Exit;
    }

    error = FT_Get_Kerning( face, left, right,
                            FT_KERNING_UNSCALED, &vec );
    if ( error )
    {
      fprintf( stderr, "FAIL %s: FT_Get_Kerning error 0x%x\n",
               path, error );
      goto Exit;
    }

    if ( vec.x != expected )
    {
      fprintf( stderr,
               "FAIL %s: kern(%u,%u) = %ld, expected %d\n",
               path, left, right, (long)vec.x, expected );
      goto Exit;
    }

    printf( "PASS %s: kern(%u,%u) = %ld\n",
            path, left, right, (long)vec.x );
    result = 0;

  Exit:
    if ( face )
      FT_Done_Face( face );
    return result;
  }


  /*
   * A malformed kern table is an optional table, so the face open
   * path tolerates its failure and simply clears the kerning flag.
   * Drive the loader directly through the sfnt interface to observe
   * the precise error code, then free whatever the loader allocated.
   */
  static int
  check_load_failure( const char*  path,
                      FT_Error     expected_error,
                      const char*  label )
  {
    FT_Face          face = NULL;
    TT_Face          tt_face;
    SFNT_Interface*  sfnt;
    FT_Stream        stream;
    FT_Error         error;
    int              result = 1;


    error = FT_New_Face( library, path, 0, &face );
    if ( error )
    {
      fprintf( stderr, "FAIL %s: unexpected FT_New_Face error 0x%x\n",
               path, error );
      return 1;
    }

    tt_face = (TT_Face)face;
    sfnt    = (SFNT_Interface*)tt_face->sfnt;
    stream  = FT_FACE_STREAM( face );

    error = sfnt->load_kern( tt_face, stream );
    if ( error != expected_error )
    {
      fprintf( stderr,
               "FAIL %s: expected load error 0x%x (%s), got 0x%x\n",
               path, expected_error, label, error );
      goto Exit;
    }

    /* FT_Done_Face runs tt_face_done_kern and frees partial state. */
    printf( "PASS %s: rejected with %s (0x%x)\n",
            path, label, error );
    result = 0;

  Exit:
    FT_Done_Face( face );
    return result;
  }


int
main( int     argc,
      char**  argv )
{
  const char*  add_path;
  const char*  override_path;
  const char*  mixed_path;
  const char*  f0_path;
  const char*  truncated_path;
  const char*  oob_path;
  const char*  stream_path;
  int          result = 0;


  if ( argc != 8 )
  {
    fprintf( stderr,
             "usage: kern2 add override mixed f0 truncated oob "
             "stream\n" );
    return 2;
  }

  add_path       = argv[1];
  override_path  = argv[2];
  mixed_path     = argv[3];
  f0_path        = argv[4];
  truncated_path = argv[5];
  oob_path       = argv[6];
  stream_path    = argv[7];

  if ( FT_Init_FreeType( &library ) )
    return 2;

  /*
   * Additive format 2 subtable, kerning array
   * [-10, -20, -30, -40] with row width 4.  Glyphs outside the
   * class ranges (glyph 0 and glyphs 5+) take class 0.
   */
  result |= check_kern( add_path, 1, 3, -10 );  /* row 0, col 0 */
  result |= check_kern( add_path, 1, 4, -20 );  /* row 0, col 2 */
  result |= check_kern( add_path, 2, 3, -30 );  /* row 1, col 0 */
  result |= check_kern( add_path, 2, 4, -40 );  /* row 1, col 2 */
  result |= check_kern( add_path, 5, 3, -10 );  /* left -> class 0 */
  result |= check_kern( add_path, 1, 6, -10 );  /* right -> class 0 */
  result |= check_kern( add_path, 0, 0, -10 );  /* both -> class 0 */

  /*
   * Second subtable carries coverage bit 3 (override): its single
   * -15 value replaces the additive subtable's result for every
   * pair, regardless of the first subtable's value.
   */
  result |= check_kern( override_path, 2, 4, -15 );
  result |= check_kern( override_path, 1, 3, -15 );

  /*
   * Mixed font.  The format 0 pair values (-100, -50) accumulate
   * with the additive format 2 table, whose out-of-range glyph 5
   * takes class 0 (-10 from row 0 col 0, -20 from row 0 col 2).
   * This also covers cross-format add semantics.
   */
  result |= check_kern( mixed_path, 1, 5, -100 + -10 );
  result |= check_kern( mixed_path, 5, 4, -50 + -20 );
  result |= check_kern( mixed_path, 1, 3, -10 );
  result |= check_kern( mixed_path, 2, 4, -40 );

  /* Format 0-only control font. */
  result |= check_kern( f0_path, 1, 5, -100 );
  result |= check_kern( f0_path, 5, 4, -50 );
  result |= check_kern( f0_path, 2, 3, 0 );    /* no matching pair */

  /*
   * Pure on-demand stream path: no format 0 table, and the vertical
   * first subtable is ignored, so only the horizontal second one
   * contributes.  Its array [-7, -9] has glyph 1 in row 0 and glyph
   * 2 in row 1, glyph 3 -> column 0 and glyph 4 -> column 2.
   */
  result |= check_kern( stream_path, 1, 3, -7 );
  result |= check_kern( stream_path, 2, 4, -9 );

  /* Distinct failure codes for the two malformed tables. */
  result |= check_load_failure( truncated_path,
                                FT_Err_Invalid_Table,
                                "Invalid_Table" );
  result |= check_load_failure( oob_path,
                                FT_Err_Invalid_Offset,
                                "Invalid_Offset" );

  FT_Done_FreeType( library );

  if ( result == 0 )
    printf( "ALL kern2 TESTS PASSED\n" );
  return result;
}
