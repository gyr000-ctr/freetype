/****************************************************************************
 *
 * ttkern.c
 *
 *   Routines to parse and access the 'kern' table for kerning (body).
 *
 * Copyright (C) 1996-2026 by
 * David Turner, Robert Wilhelm, and Werner Lemberg.
 *
 * This file is part of the FreeType project, and may only be used,
 * modified, and distributed under the terms of the FreeType project
 * license, LICENSE.TXT.  By continuing to use, modify, or distribute
 * this file you indicate that you have read the license and
 * understand and accept it fully.
 *
 */


#include <freetype/internal/ftdebug.h>
#include <freetype/internal/ftstream.h>
#include <freetype/tttags.h>
#include "ttkern.h"

#include "sferrors.h"


  /**************************************************************************
   *
   * The macro FT_COMPONENT is used in trace mode.  It is an implicit
   * parameter of the FT_TRACE() and FT_ERROR() macros, used to print/log
   * messages during execution.
   */
#undef  FT_COMPONENT
#define FT_COMPONENT  ttkern


#undef  TT_KERN_INDEX
#define TT_KERN_INDEX( g1, g2 )  ( ( (FT_ULong)(g1) << 16 ) | (g2) )


  /*
   * A format 2 (class-based) kerning subtable keeps its data in the
   * stream; only the little descriptor in `face->kern2_subtables` is
   * kept resident.  The following two helpers perform the on-demand
   * stream reads.  The structural validation in `tt_face_load_kern'
   * guarantees that every position they access lies within the
   * subtable, so a failing read only returns a zero value.
   */


  /**************************************************************************
   *
   * @Function:
   *   kern2_read_class
   *
   * @Description:
   *   Look up the class value for a glyph in a format 2 class table.
   *   Glyphs outside the table's glyph range belong to class 0, as do
   *   glyphs covered by a zero-length table.
   *
   * @Input:
   *   stream ::
   *     The input stream, positioned arbitrarily.
   *
   *   class_offset ::
   *     Absolute stream position of the class table.
   *
   *   data_limit ::
   *     First position past the enclosing subtable.
   *
   *   glyph ::
   *     The glyph index to look up.
   *
   * @Return:
   *   The unsigned 16-bit class value.  Zero on a stream failure.
   */
  static FT_UInt
  kern2_read_class( FT_Stream  stream,
                    FT_ULong   class_offset,
                    FT_ULong   data_limit,
                    FT_UInt    glyph )
  {
    FT_Error  error;
    FT_Byte   hdr[4];
    FT_Byte   entry_buf[2];
    FT_Byte*  p = hdr;
    FT_ULong  entry_pos;
    FT_UInt   first_glyph, num_glyphs;
    FT_UInt   result = 0;


    if ( FT_STREAM_READ_AT( class_offset, hdr, 4 ) )
      return 0;

    first_glyph = FT_NEXT_USHORT( p );
    num_glyphs  = FT_NEXT_USHORT( p );

    /* written as a sum to avoid unsigned wrap in the glyph delta */
    if ( glyph < first_glyph ||
         (FT_ULong)glyph >= (FT_ULong)first_glyph + num_glyphs )
      return 0;

    /*
     * The entry's position was verified against `data_limit' while
     * loading the face; check it defensively anyway.
     */
    entry_pos = class_offset + 4 +
                  2 * (FT_ULong)( glyph - first_glyph );
    if ( entry_pos + 2 > data_limit )
      return 0;

    if ( FT_STREAM_READ_AT( entry_pos, entry_buf, 2 ) )
      return 0;

    p      = entry_buf;
    result = FT_NEXT_USHORT( p );

    return result;
  }


  /**************************************************************************
   *
   * @Function:
   *   tt_kern2_get_value
   *
   * @Description:
   *   Return the kerning value of a format 2 subtable for a glyph pair.
   *   Both class values are byte offsets; the value is found at
   *
   *     kerningArray + leftClass + rightClass
   *
   *   where the left class value already carries the row offset.
   *
   * @Input:
   *   face ::
   *     The target face object.
   *
   *   sub ::
   *     A validated format 2 subtable descriptor.
   *
   *   left_glyph ::
   *     The left glyph index.
   *
   *   right_glyph ::
   *     The right glyph index.
   *
   * @Return:
   *   The signed kerning value in font units, or zero if it cannot be
   *   read.
   */
  static FT_Int
  tt_kern2_get_value( TT_Face                 face,
                      TT_Kern2SubtableRec*    sub,
                      FT_UInt                 left_glyph,
                      FT_UInt                 right_glyph )
  {
    FT_Stream  stream = face->root.stream;
    FT_Error   error;
    FT_Byte    buf[2];
    FT_Byte*   p;
    FT_UInt    left_class, right_class;
    FT_ULong   entry;
    FT_Int     result = 0;


    left_class  = kern2_read_class( stream, sub->left_offset,
                                    sub->data_limit, left_glyph );
    right_class = kern2_read_class( stream, sub->right_offset,
                                    sub->data_limit, right_glyph );

    entry = sub->array_offset + (FT_ULong)left_class +
                              (FT_ULong)right_class;

    if ( entry + 2 > sub->data_limit )
      return 0;

    if ( FT_STREAM_READ_AT( entry, buf, 2 ) )
      return 0;

    p      = buf;
    result = FT_PEEK_SHORT( p );

    return result;
  }


  /**************************************************************************
   *
   * @Function:
   *   tt_kern2_validate
   *
   * @Description:
   *   Validate a horizontal format 2 kerning subtable and fill a
   *   descriptor for later on-demand access.  The stream is read in
   *   small chunks; the subtable data itself is never copied.
   *
   *   Two distinct failure codes are produced:
   *
   *   - Invalid_Table for truncated headers and class tables, and for
   *     class table offsets pointing outside the subtable;
   *   - Invalid_Offset for class values whose kerning array index lies
   *     outside the subtable.
   *
   * @Input:
   *   face ::
   *     The target face object.
   *
   *   stream ::
   *     The input stream.
   *
   *   subtable_offset ::
   *     Absolute stream position of the subtable header.
   *
   *   subtable_length ::
   *     The declared subtable length, already clamped to the kern
   *     table's end by the caller.
   *
   *   coverage ::
   *     The subtable's coverage field.
   *
   * @Output:
   *   sub ::
   *     The descriptor to fill.
   *
   * @Return:
   *   FreeType error code.  0 means success.
   */
  static FT_Error
  tt_kern2_validate( TT_Face                 face,
                     FT_Stream               stream,
                     FT_ULong                subtable_offset,
                     FT_ULong                subtable_length,
                     FT_UInt                 coverage,
                     TT_Kern2SubtableRec*    sub )
  {
    FT_Byte   buf[8];
    FT_Byte*  p;
    FT_ULong  data_limit  = subtable_offset + subtable_length;
    FT_ULong  left_rel, right_rel, array_rel, entry;
    FT_UInt   row_width, nn;
    FT_UInt   class_info[2][2];  /* firstGlyph, nGlyphs per class  */
    FT_ULong  class_offsets[2];
    FT_Error  error;

    FT_UNUSED( face );


    /* the 6-byte subtable header plus the 8-byte format 2 header */
    if ( subtable_length < 14 )
      return FT_THROW( Invalid_Table );

    if ( FT_STREAM_READ_AT( subtable_offset + 6, buf, 8 ) )
      return FT_THROW( Invalid_Table );

    p         = buf;
    row_width = FT_NEXT_USHORT( p );
    left_rel  = FT_NEXT_USHORT( p );
    right_rel = FT_NEXT_USHORT( p );
    array_rel = FT_NEXT_USHORT( p );

    if ( row_width < 2 )
      return FT_THROW( Invalid_Table );

    /* all three offsets are relative to the subtable start */
    if ( left_rel >= subtable_length || right_rel >= subtable_length ||
         array_rel >= subtable_length )
      return FT_THROW( Invalid_Offset );

    class_offsets[0] = subtable_offset + left_rel;
    class_offsets[1] = subtable_offset + right_rel;

    for ( nn = 0; nn < 2; nn++ )
    {
      FT_ULong  header_pos = class_offsets[nn];


      /* the class table header plus every entry must fit */
      if ( header_pos + 4 > data_limit )
        return FT_THROW( Invalid_Table );

      if ( FT_STREAM_READ_AT( header_pos, buf, 4 ) )
        return FT_THROW( Invalid_Table );

      p                 = buf;
      class_info[nn][0] = FT_NEXT_USHORT( p );  /* firstGlyph */
      class_info[nn][1] = FT_NEXT_USHORT( p );  /* nGlyphs    */

      if ( header_pos + 4 + 2 * (FT_ULong)class_info[nn][1] >
             data_limit )
        return FT_THROW( Invalid_Table );
    }

    /*
     * Every class value is a byte offset into the kerning array; the
     * value for a pair is found at `array + leftClass + rightClass'.
     * Check all entries of both class tables against the subtable
     * boundary so that later lookups cannot run past it.  Left class
     * values are multiples of the row width, right class values stay
     * within a row.
     */
    for ( nn = 0; nn < 2; nn++ )
    {
      FT_UInt  num_glyphs = class_info[nn][1];
      FT_UInt  kk;


      for ( kk = 0; kk < num_glyphs; kk++ )
      {
        FT_ULong  entry_pos = class_offsets[nn] + 4 + 2 * (FT_ULong)kk;
        FT_UInt   class_value;


        if ( FT_STREAM_READ_AT( entry_pos, buf, 2 ) )
          return FT_THROW( Invalid_Table );

        p           = buf;
        class_value = FT_NEXT_USHORT( p );

        if ( nn == 0 )
        {
          /* left class: a whole-row offset, a multiple of rowWidth */
          if ( class_value % row_width != 0 )
            return FT_THROW( Invalid_Offset );

          /* the last value of this row must stay inside the subtable */
          entry = subtable_offset + array_rel + class_value + row_width;
        }
        else
        {
          /* right class: the column offset must stay within a row */
          if ( class_value >= row_width )
            return FT_THROW( Invalid_Offset );

          /* the value at this column must stay inside the subtable */
          entry = subtable_offset + array_rel + class_value + 2;
        }

        /* compare against the subtable end */
        if ( entry > data_limit )
          return FT_THROW( Invalid_Offset );
      }
    }

    /* the kerning array must contain at least one value */
    if ( subtable_offset + array_rel + 2 > data_limit )
      return FT_THROW( Invalid_Table );

    sub->mask         = 0;  /* set by the caller */
    sub->coverage     = coverage;
    sub->data_limit   = data_limit;
    sub->left_offset  = class_offsets[0];
    sub->right_offset = class_offsets[1];
    sub->array_offset = subtable_offset + array_rel;

    return FT_Err_Ok;
  }


  FT_LOCAL_DEF( FT_Error )
  tt_face_load_kern( TT_Face    face,
                     FT_Stream  stream )
  {
    FT_Error   error;
    FT_Memory  memory = stream->memory;
    FT_ULong   table_size, table_start;
    FT_Byte    header[4];
    FT_Byte*   p;
    FT_UInt    nn, num_tables;
    FT_UInt32  avail = 0, ordered = 0;
    FT_Bool    have_format0 = 0;

    TT_Kern2SubtableRec*  kern2 = NULL;
    FT_UInt               num_kern2 = 0;


    /* the kern table is optional; exit silently if it is missing */
    error = face->goto_table( face, TTAG_kern, stream, &table_size );
    if ( error )
      goto Exit;

    if ( table_size < 4 )  /* the case of a malformed table */
    {
      FT_ERROR(( "tt_face_load_kern:"
                 " kerning table is too small - ignored\n" ));
      error = FT_THROW( Table_Missing );
      goto Exit;
    }

    table_start = FT_STREAM_POS();

    if ( FT_STREAM_READ_AT( table_start, header, 4 ) )
      goto Exit;

    p = header;
    p += 2; /* skip version */
    num_tables = FT_NEXT_USHORT( p );

    if ( num_tables > 32 ) /* we only support up to 32 sub-tables */
      num_tables = 32;

    if ( FT_NEW_ARRAY( kern2, num_tables ) )
      goto Exit;

    /*
     * First pass: walk the subtable headers with small stream reads.
     * Format 0 tables need the whole kern table resident, exactly as
     * before; format 2 tables are validated and described without
     * copying their data.
     */
    {
      FT_ULong  pos = table_start + 4;
      FT_ULong  table_limit = table_start + table_size;


      for ( nn = 0; nn < num_tables; nn++ )
      {
        FT_Byte   sub_header[6];
        FT_Byte*  q;
        FT_UInt   length, coverage, format;
        FT_ULong  next_pos;


        if ( pos + 6 > table_limit )
          break;

        if ( FT_STREAM_READ_AT( pos, sub_header, 6 ) )
          break;

        q        = sub_header;
        q       += 2; /* skip version */
        length   = FT_NEXT_USHORT( q );
        coverage = FT_NEXT_USHORT( q );

        if ( length < 6 )  /* cannot even hold the subtable header */
          break;

        next_pos = pos + length;
        if ( next_pos > table_limit )  /* handle broken table */
          next_pos = table_limit;

        format = coverage >> 8;

        if ( format == 0 && ( coverage & 3U ) == 0x0001 )
          have_format0 = 1;

        if ( format == 2 && ( coverage & 3U ) == 0x0001 )
        {
          TT_Kern2SubtableRec*  sub = kern2 + num_kern2;
          FT_ULong              sub_length = next_pos - pos;


          error = tt_kern2_validate( face, stream, pos, sub_length,
                                     coverage, sub );
          if ( error )
            goto Fail;

          sub->mask = (FT_UInt32)1UL << nn;
          num_kern2++;
        }

        pos = next_pos;
      }

      /* remember how many subtable headers were actually walkable */
      num_tables = nn;
    }

    if ( have_format0 )
    {
      FT_Byte*  p_limit;


      /*
       * Format 0 handling is unchanged: extract the whole kern table
       * and parse the pair subtables in memory.  The on-demand reads
       * above moved the stream position, so seek back to the table
       * start first.
       */
      if ( FT_STREAM_SEEK( table_start )                  ||
           FT_FRAME_EXTRACT( table_size, face->kern_table ) )
      {
        FT_ERROR(( "tt_face_load_kern:"
                   " could not extract kerning table\n" ));
        goto Fail;
      }

      face->kern_table_size = table_size;

      p       = face->kern_table;
      p_limit = p + table_size;

      p         += 2; /* skip version */
      num_tables = FT_NEXT_USHORT( p );

      if ( num_tables > 32 ) /* we only support up to 32 sub-tables */
        num_tables = 32;

      for ( nn = 0; nn < num_tables; nn++ )
      {
        FT_UInt    num_pairs, length, coverage, format;
        FT_Byte*   p_next;
        FT_UInt32  mask = (FT_UInt32)1UL << nn;


        if ( p + 6 > p_limit )
          break;

        p_next = p;

        p       += 2; /* skip version */
        length   = FT_NEXT_USHORT( p );
        coverage = FT_NEXT_USHORT( p );

        if ( length <= 6 + 8 )
          break;

        p_next += length;

        if ( p_next > p_limit )  /* handle broken table */
          p_next = p_limit;

        format = coverage >> 8;

        /* we currently only support format 0 kerning tables here */
        if ( format != 0 )
          goto NextTable0;

        /* only use horizontal kerning tables */
        if ( ( coverage & 3U ) != 0x0001 ||
             p + 8 > p_next              )
          goto NextTable0;

        num_pairs = FT_NEXT_USHORT( p );
        p        += 6;

        if ( ( p_next - p ) < 6 * (int)num_pairs ) /* handle broken count */
          num_pairs = (FT_UInt)( ( p_next - p ) / 6 );

        avail |= mask;

        /*
         * Now check whether the pairs in this table are ordered.
         * We then can use binary search.
         */
        if ( num_pairs > 0 )
        {
          FT_ULong  count;
          FT_ULong  old_pair;


          old_pair = FT_NEXT_ULONG( p );
          p       += 2;

          for ( count = num_pairs - 1; count > 0; count-- )
          {
            FT_UInt32  cur_pair;


            cur_pair = FT_NEXT_ULONG( p );
            if ( cur_pair < old_pair )
              break;

            p += 2;
            old_pair = cur_pair;
          }

          if ( count == 0 )
            ordered |= mask;
        }

      NextTable0:
        p = p_next;
      }

      num_tables = nn;
    }

    /* mark the validated format 2 subtables as available */
    for ( nn = 0; nn < num_kern2; nn++ )
      avail |= kern2[nn].mask;

    /*
     * Hand the descriptors over to the face.  On a later error below
     * they would be freed in `tt_face_done_kern'; here nothing else
     * can fail, so publish them directly.
     */
    face->kern2_subtables    = kern2;
    face->num_kern2_subtables = num_kern2;
    kern2                     = NULL;

    face->num_kern_tables = num_tables;
    face->kern_avail_bits = avail;
    face->kern_order_bits = ordered;

  Exit:
    return error;

  Fail:
    FT_FRAME_RELEASE( face->kern_table );
    face->kern_table_size = 0;
    FT_FREE( kern2 );
    goto Exit;
  }


  FT_LOCAL_DEF( void )
  tt_face_done_kern( TT_Face  face )
  {
    FT_Stream  stream = face->root.stream;
    FT_Memory memory  = stream->memory;


    FT_FRAME_RELEASE( face->kern_table );
    face->kern_table_size = 0;
    face->num_kern_tables = 0;
    face->kern_avail_bits = 0;
    face->kern_order_bits = 0;

    FT_FREE( face->kern2_subtables );
    face->num_kern2_subtables = 0;
  }


  FT_LOCAL_DEF( FT_Int )
  tt_face_get_kerning( TT_Face  face,
                       FT_UInt  left_glyph,
                       FT_UInt  right_glyph )
  {
    FT_Int   result = 0;
    FT_UInt  count, mask;

    FT_Byte*  p;
    FT_Byte*  p_limit;


    if ( !face->kern_table && face->num_kern2_subtables == 0 )
      return result;

    if ( face->kern_table )
    {
      p       = face->kern_table;
      p_limit = p + face->kern_table_size;

      p   += 4;
      mask = 0x0001;

      for ( count = face->num_kern_tables;
            count > 0 && p + 6 <= p_limit;
            count--, mask <<= 1 )
      {
        FT_Byte*  base     = p;
        FT_Byte*  next;
        FT_UInt   version  = FT_NEXT_USHORT( p );
        FT_UInt   length   = FT_NEXT_USHORT( p );
        FT_UInt   coverage = FT_NEXT_USHORT( p );
        FT_UInt   num_pairs;
        FT_Int    value    = 0;

        FT_UNUSED( version );


        next = base + length;

        if ( next > p_limit )  /* handle broken table */
          next = p_limit;

        if ( ( face->kern_avail_bits & mask ) == 0 )
          goto NextTable;

        switch ( coverage >> 8 )
        {
        case 0:
          {
            FT_ASSERT( p + 8 <= next ); /* tested in tt_face_load_kern */

            num_pairs = FT_NEXT_USHORT( p );
            p        += 6;

            if ( ( next - p ) < 6 * (int)num_pairs ) /* broken count */
              num_pairs = (FT_UInt)( ( next - p ) / 6 );

            {
              FT_ULong  key0 = TT_KERN_INDEX( left_glyph, right_glyph );


              if ( face->kern_order_bits & mask )   /* binary search */
              {
                FT_UInt   min = 0;
                FT_UInt   max = num_pairs;


                while ( min < max )
                {
                  FT_UInt   mid = ( min + max ) >> 1;
                  FT_Byte*  q   = p + 6 * mid;
                  FT_ULong  key;


                  key = FT_NEXT_ULONG( q );

                  if ( key == key0 )
                  {
                    value = FT_PEEK_SHORT( q );
                    goto Found;
                  }
                  if ( key < key0 )
                    min = mid + 1;
                  else
                    max = mid;
                }
              }
              else /* linear search */
              {
                FT_UInt  count2;


                for ( count2 = num_pairs; count2 > 0; count2-- )
                {
                  FT_ULong  key = FT_NEXT_ULONG( p );


                  if ( key == key0 )
                  {
                    value = FT_PEEK_SHORT( p );
                    goto Found;
                  }
                  p += 2;
                }
              }
            }
          }
          break;

        case 2:
          {
            TT_Kern2SubtableRec*  sub;
            FT_UInt               kk;


            for ( kk = 0; kk < face->num_kern2_subtables; kk++ )
            {
              sub = face->kern2_subtables + kk;
              if ( sub->mask == mask )
              {
                value = tt_kern2_get_value( face, sub,
                                            left_glyph, right_glyph );
                goto Found;
              }
            }
          }
          break;

        default:
          ;
        }

        goto NextTable;

      Found:
        if ( coverage & 8 ) /* override or add */
          result = value;
        else
          result += value;

      NextTable:
        p = next;
      }
    }
    else
    {
      /*
       * No resident kern table: all supported subtables are format 2
       * and are read from the stream on demand.
       */
      for ( count = 0; count < face->num_kern2_subtables; count++ )
      {
        TT_Kern2SubtableRec*  sub = face->kern2_subtables + count;
        FT_Int                value;


        value = tt_kern2_get_value( face, sub,
                                    left_glyph, right_glyph );

        if ( sub->coverage & 8 ) /* override or add */
          result = value;
        else
          result += value;
      }
    }

    return result;
  }

#undef TT_KERN_INDEX

/* END */
